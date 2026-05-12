"""Ingest pipeline: fetch → strip → chunk → embed → upsert.

Public surface
--------------
- `chunk_text(text, max_tokens)` — split text into token-bounded chunks
- `ingest(ticker, *, form_type, period, fiscal_year)` — full pipeline; returns chunk count
"""

from __future__ import annotations

import tiktoken

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
) -> int:
    """Fetch, chunk, embed, and upsert a SEC filing.

    Supported form types: 10-K, 10-Q, 8-K, 20-F, DEF 14A.
    Provide either `period` (e.g. "FY2024", "2024-05-10") or `fiscal_year` as int.
    The period stored in the DB is always the actual EDGAR reportDate (YYYY-MM-DD).
    Returns the number of chunks written to the database.
    """
    search_period = _build_search_period(fiscal_year, period)
    # HTTP and CPU work outside the DB transaction.
    company = EdgarCompanyInfo.model_validate(company_info_for_ticker(ticker))
    filing = EdgarFiling.model_validate(fetch_filing(ticker, form_type, search_period))
    # Canonical stored period is the actual EDGAR reportDate as a typed date, not a string.
    stored_period = filing.report_date
    texts = chunk_text(filing.text)
    if not texts:
        raise ValueError(
            f"No text extracted from {ticker} {stored_period} {form_type}"
        )

    vectors = _embed_batched(texts)

    # Guard: embedding API must return exactly one vector per chunk.
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: got {len(vectors)} vectors for {len(texts)} chunks"
        )

    # Single atomic transaction: company upsert → filing_type resolve → document upsert → chunks.
    # psycopg v3 with-block auto-commits on success, auto-rollbacks on any exception.
    with get_conn() as conn:
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

        for idx, (text, vector) in enumerate(zip(texts, vectors, strict=True)):
            token_count = len(_ENCODING.encode(text))
            conn.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, tokens, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (doc_id, idx, text, token_count, vector),
            )

    return len(texts)
