"""Seed a minimal fixture into the database for Wave 1b local testing.

Usage:
    uv run python data/fixtures/seed.py

Inserts one fake document (ticker=DEMO) and three chunks with real embeddings
so retrieve.py and rag.py can be tested without EDGAR ingestion.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import config, db  # noqa: E402 — path manipulation above required
from src.embed import embed  # noqa: E402

CHUNKS = [
    "DEMO Corp reported total revenue of $12.5 billion for fiscal year 2024, "
    "representing a 8% increase compared to fiscal year 2023.",
    "Research and development expenses for fiscal year 2024 were $2.1 billion, "
    "up from $1.8 billion in the prior year, reflecting continued investment in innovation.",
    "Net income for fiscal year 2024 was $3.2 billion, yielding a net profit margin "
    "of approximately 25.6% on total revenues.",
]


def seed() -> None:
    db.bootstrap()
    embeddings = embed(CHUNKS, input_type="passage")

    with db.get_conn() as conn:
        # Upsert document — idempotent via ON CONFLICT.
        row = conn.execute(
            """
            INSERT INTO documents (ticker, filing_type, period, accession)
            VALUES ('DEMO', '10-K', 'FY2024', 'demo-accession-0001')
            ON CONFLICT (accession) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                filing_type = EXCLUDED.filing_type,
                period = EXCLUDED.period
            RETURNING id
            """,
        ).fetchone()
        doc_id = row[0]

        # Delete existing chunks for this document to stay idempotent.
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

        for idx, (text, vec) in enumerate(zip(CHUNKS, embeddings)):
            conn.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, tokens, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (doc_id, idx, text, len(text.split()), vec),
            )

        conn.commit()
    print(f"Seeded document id={doc_id} with {len(CHUNKS)} chunks (ticker=DEMO, period=FY2024)")


if __name__ == "__main__":
    seed()
