"""Ingest pipeline: fetch → strip → chunk → embed → upsert.

Public surface
--------------
- `chunk_text(text, max_tokens)` — fixed paragraph/token chunking (Wave 1c)
- `chunk_sentence_window(text, ...)` — overlapping sentence windows (Wave 3a)
- `chunk_parent_doc(text, ...)` — small children + larger parent context (Wave 3a)
- `build_chunks(text, strategy)` — strategy dispatch → list[(content, metadata)]
- `ingest(ticker, *, form_type, period, fiscal_year, chunk_strategy)` — full pipeline
"""

from __future__ import annotations

import re

import tiktoken
from psycopg.types.json import Jsonb

from src.clients.edgar import EdgarCompanyInfo, EdgarFiling
from src.db import get_conn
from src.embed import embed
from src.financial.edgar import company_info_for_ticker, fetch_filing

_ENCODING = tiktoken.get_encoding("cl100k_base")
# NVIDIA nv-embedqa-e5-v5 has a 512-token context window (WordPiece tokenizer).
# EDGAR filings contain dense numbers/codes that WordPiece splits more finely
# than cl100k_base (observed ratio ~1.4-1.5x).  A 300-token cl100k budget
# reliably stays under the 512 NVIDIA limit.
# 300 cl100k tokens ≈ 450 WordPiece tokens
_MAX_TOKENS = 300
_EMBED_BATCH = 32

# Single source of truth for selectable chunking strategies (CHUNK_STRATEGY env,
# --chunk-strategy CLI flag, build_chunks dispatch all validate against this).
VALID_CHUNK_STRATEGIES = ("fixed", "sentence_window", "section", "parent_doc")


def validate_chunk_strategy(strategy: str) -> str:
    """Return the normalized strategy or raise ValueError if it isn't selectable."""
    normalized = strategy.lower()
    if normalized not in VALID_CHUNK_STRATEGIES:
        raise ValueError(
            f"Unknown chunk strategy {strategy!r}; expected one of "
            f"{', '.join(VALID_CHUNK_STRATEGIES)}"
        )
    return normalized


def chunk_text(text: str, max_tokens: int = _MAX_TOKENS) -> list[str]:
    """Split text into chunks where each chunk is at most max_tokens.

    Splits on paragraph boundaries (\\n\\n) first; falls back to token-level
    split for paragraphs that are themselves too long.
    """
    if max_tokens <= 0:
        raise ValueError(f"max_tokens must be positive, got {max_tokens}")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_count = 0

    def _flush() -> None:
        nonlocal current, current_count
        if current:
            chunks.append(" ".join(current))
            current, current_count = [], 0

    for para in paragraphs:
        tokens = _ENCODING.encode(para)
        count = len(tokens)

        if count > max_tokens:
            # Flush buffer before splitting the oversized paragraph.
            _flush()
            # Overlap of 10% of max_tokens to preserve cross-boundary context.
            stride = max(1, int(max_tokens * 0.9))
            start = 0
            while start < count:
                window = tokens[start : start + max_tokens]
                chunks.append(_ENCODING.decode(window))
                start += stride
        else:
            # Would the joined string exceed max_tokens?  Check the real encoded
            # length of the candidate join, not just the accumulated count.
            candidate = " ".join(current + [para])
            if len(_ENCODING.encode(candidate)) > max_tokens:
                _flush()
            current.append(para)
            current_count = len(_ENCODING.encode(" ".join(current)))

    _flush()
    return [c for c in chunks if c.strip()]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    """Split text into sentences across paragraph boundaries (filing-grade, not perfect)."""
    out: list[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            out.extend(s.strip() for s in _SENT_SPLIT.split(para) if s.strip())
    return out


def chunk_sentence_window(
    text: str, *, window: int = 5, stride: int = 4, max_tokens: int = _MAX_TOKENS
) -> list[str]:
    """Overlapping sentence-window chunks.

    Each chunk is `window` consecutive sentences advanced by `stride`
    (overlap = window - stride), capped at max_tokens. Sentence boundaries keep a
    chunk's narrative self-contained, unlike fixed token windows that cut mid-clause.
    """
    if window <= 0 or stride <= 0:
        raise ValueError("window and stride must be positive")
    sents = _sentences(text)
    chunks: list[str] = []
    for start in range(0, len(sents), stride):
        window_sents = sents[start : start + window]
        if not window_sents:
            continue
        joined = " ".join(window_sents)
        tokens = _ENCODING.encode(joined)
        if len(tokens) > max_tokens:
            joined = _ENCODING.decode(tokens[:max_tokens])
        chunks.append(joined)
        if start + window >= len(sents):
            break
    return [c for c in chunks if c.strip()]


# 10-K structural headings: "Item 1.", "Item 1A.", "Item 7.", "PART II", etc.
_HEADING_RE = re.compile(r"^\s*(part\s+[ivx]+|item\s+\d+[a-c]?)\b", re.IGNORECASE)


def chunk_section_aware(text: str, *, max_tokens: int = _MAX_TOKENS) -> list[str]:
    """Section/layout-aware chunks with heading prefixes (Wave 3g).

    Splits the filing at 10-K structural headings (Item / Part) so a chunk never
    spans two sections, then chunks each section's body under the token budget and
    prepends the section heading to every resulting chunk. The heading gives the
    embedding (and the reader) the section context a bare token window loses.
    Falls back to fixed chunking when no headings are detected.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    body: list[str] = []
    for para in paragraphs:
        # A short paragraph starting with Item/Part is a heading delimiter.
        if _HEADING_RE.match(para) and len(para) < 250:
            if body:
                sections.append((heading, body))
            heading, body = para, []
        else:
            body.append(para)
    if body:
        sections.append((heading, body))

    if not any(h for h, _ in sections):  # no headings found → fixed chunking
        return chunk_text(text, max_tokens=max_tokens)

    chunks: list[str] = []
    for head, paras in sections:
        body_text = "\n\n".join(paras).strip()
        if not body_text:
            continue
        prefix = (head[:160] + "\n") if head else ""
        budget = max(64, max_tokens - len(_ENCODING.encode(prefix)))
        for sub in chunk_text(body_text, max_tokens=budget):
            chunks.append(f"{prefix}{sub}")
    return [c for c in chunks if c.strip()]


def chunk_parent_doc(
    text: str, *, child_tokens: int = 120, parent_tokens: int = 500
) -> list[tuple[str, str]]:
    """Hierarchical parent-document chunks: (child_text, parent_text) pairs.

    The small child is embedded and ranked (precise match); the larger parent is
    stored for use as generation context (enough surrounding narrative to answer).
    Returns one pair per child; children of the same parent share parent_text.
    """
    pairs: list[tuple[str, str]] = []
    for parent in chunk_text(text, max_tokens=parent_tokens):
        for child in chunk_text(parent, max_tokens=child_tokens):
            pairs.append((child, parent))
    return pairs


def build_chunks(text: str, strategy: str = "fixed") -> list[tuple[str, dict]]:
    """Strategy dispatch → list of (content, metadata) pairs ready to embed/store.

    - fixed:            paragraph/token chunks, metadata {}
    - sentence_window:  overlapping sentence windows, metadata {}
    - parent_doc:       child content embedded, metadata {"parent_text": ...}
    """
    strategy = validate_chunk_strategy(strategy)
    if strategy == "fixed":
        return [(c, {}) for c in chunk_text(text)]
    if strategy == "sentence_window":
        return [(c, {}) for c in chunk_sentence_window(text)]
    if strategy == "section":
        return [(c, {}) for c in chunk_section_aware(text)]
    # parent_doc
    return [(child, {"parent_text": parent}) for child, parent in chunk_parent_doc(text)]


def _embed_batched(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        vectors.extend(embed(texts[i : i + _EMBED_BATCH], input_type="passage"))
    return vectors


def _build_search_period(fiscal_year: int | None, period: str | None) -> str:
    """Build the EDGAR search period string (used only to locate the filing, not for storage).

    The stored period is always filing["report_date"] (the actual YYYY-MM-DD from EDGAR).
    """
    if period:
        return period
    if fiscal_year is not None:
        return f"FY{fiscal_year}"
    raise ValueError("Either period or fiscal_year must be provided")


def ingest(
    ticker: str,
    *,
    form_type: str = "10-K",
    period: str | None = None,
    fiscal_year: int | None = None,
    chunk_strategy: str | None = None,
) -> int:
    """Fetch, chunk, embed, and upsert a SEC filing.

    Supported form types: 10-K, 10-Q, 8-K, 20-F, DEF 14A.
    Provide either `period` (e.g. "FY2024", "2024-05-10") or `fiscal_year` as int.
    The period stored in the DB is always the actual EDGAR reportDate (YYYY-MM-DD).
    chunk_strategy: fixed | sentence_window | section | parent_doc
    (defaults to CHUNK_STRATEGY env).
    Returns the number of chunks written to the database.
    """
    from src import config

    # Validate the strategy up front so a typo fails immediately, before any
    # EDGAR fetch / embedding work.
    strategy = validate_chunk_strategy(chunk_strategy or config.chunk_strategy())
    search_period = _build_search_period(fiscal_year, period)
    # HTTP and CPU work outside the DB transaction.
    company = EdgarCompanyInfo.model_validate(company_info_for_ticker(ticker))
    filing = EdgarFiling.model_validate(fetch_filing(ticker, form_type, search_period))
    # Canonical stored period is the actual EDGAR reportDate as a typed date, not a string.
    stored_period = filing.report_date
    records = build_chunks(filing.text, strategy)
    if not records:
        raise ValueError(
            f"No text extracted from {ticker} {stored_period} {form_type}"
        )
    texts = [content for content, _ in records]
    metadatas = [meta for _, meta in records]

    vectors = _embed_batched(texts)

    # Guard: embedding API must return exactly one vector per chunk.
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: got {len(vectors)} vectors for {len(texts)} chunks"
        )

    # Single atomic transaction: company upsert → filing_type resolve → document upsert → chunks.
    # The shared connection runs in autocommit, so wrap the multi-statement write in an
    # explicit transaction() — it commits on success and rolls back on any exception.
    with get_conn() as conn, conn.transaction():
        # Upsert company — updates CIK/name if ticker already exists.
        row = conn.execute(
            """
            INSERT INTO companies (ticker, cik, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE
                SET cik  = COALESCE(EXCLUDED.cik,  companies.cik),
                    name = COALESCE(EXCLUDED.name, companies.name)
            RETURNING id
            """,
            (ticker.upper(), company.cik, company.name),
        ).fetchone()
        company_id = row[0]

        # Resolve filing_type_id — seeded by migration; upsert handles any gap defensively.
        # DO UPDATE SET code = EXCLUDED.code is a no-op that lets RETURNING work on conflict.
        row = conn.execute(
            """
            INSERT INTO filing_types (code)
            VALUES (%s)
            ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
            RETURNING id
            """,
            (form_type,),
        ).fetchone()
        filing_type_id = row[0]

        row = conn.execute(
            """
            INSERT INTO documents (company_id, filing_type_id, period, filed_at, accession, raw_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO UPDATE
                SET company_id     = EXCLUDED.company_id,
                    filing_type_id = EXCLUDED.filing_type_id,
                    period         = EXCLUDED.period,
                    filed_at       = EXCLUDED.filed_at,
                    raw_url        = EXCLUDED.raw_url
            RETURNING id
            """,
            (
                company_id,
                filing_type_id,
                stored_period,
                filing.filed_at,
                filing.accession,
                filing.raw_url,
            ),
        ).fetchone()
        doc_id = row[0]

        # Replace all chunks so re-ingestion is idempotent.
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

        for idx, (text, vector, meta) in enumerate(
            zip(texts, vectors, metadatas, strict=True)
        ):
            token_count = len(_ENCODING.encode(text))
            conn.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, tokens, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s::vector, %s)
                """,
                (doc_id, idx, text, token_count, vector, Jsonb(meta)),
            )

    return len(texts)
