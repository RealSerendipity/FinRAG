"""Ingest pipeline: fetch → strip → chunk → embed → upsert.

Public surface
--------------
- `chunk_text(text, max_tokens)` — split text into token-bounded chunks
- `ingest(ticker, fiscal_year)` — full pipeline; returns number of chunks stored
"""

from __future__ import annotations

import tiktoken

from src.db import get_conn
from src.embed import embed
from src.financial.edgar import fetch_10k

_ENCODING = tiktoken.get_encoding("cl100k_base")
# NVIDIA nv-embedqa-e5-v5 has a 512-token context window (WordPiece tokenizer).
# EDGAR filings contain dense numbers/codes that WordPiece splits more finely
# than cl100k_base (observed ratio ~1.4-1.5x).  A 300-token cl100k budget
# reliably stays under the 512 NVIDIA limit.
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


def ingest(ticker: str, fiscal_year: int) -> int:
    """Fetch, chunk, embed, and upsert a 10-K filing.

    `fiscal_year` is matched against the filing's period-of-report (reportDate),
    not the calendar year the document was filed.

    Returns the number of chunks written to the database.
    """
    filing = fetch_10k(ticker, fiscal_year)
    period = f"FY{fiscal_year}"
    texts = chunk_text(filing["text"])
    if not texts:
        raise ValueError(f"No text extracted from {ticker} FY{fiscal_year} 10-K")

    vectors = _embed_batched(texts)

    # Guard: embedding API must return exactly one vector per chunk.
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: got {len(vectors)} vectors for {len(texts)} chunks"
        )

    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO documents (ticker, filing_type, period, filed_at, accession, raw_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO UPDATE
                SET filed_at = EXCLUDED.filed_at,
                    raw_url  = EXCLUDED.raw_url
            RETURNING id
            """,
            (
                ticker.upper(),
                "10-K",
                period,
                filing["filed_at"],
                filing["accession"],
                filing["raw_url"],
            ),
        ).fetchone()
        doc_id = row[0]

        # Replace all chunks so re-ingestion is idempotent.
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

        for idx, (text, vector) in enumerate(zip(texts, vectors)):
            token_count = len(_ENCODING.encode(text))
            conn.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, tokens, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (doc_id, idx, text, token_count, vector),
            )

    return len(texts)
