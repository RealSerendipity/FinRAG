"""Seed a minimal fixture into the database for Wave 1b local testing.

Usage:
    uv run python data/fixtures/seed.py

Inserts one fake document (ticker=DEMO) and three chunks with real embeddings
so retrieve.py and rag.py can be tested without EDGAR ingestion.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

# Allow running as a script from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src import db  # noqa: E402 — path manipulation above required
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
        # Upsert company — DEMO has no real CIK.
        row = conn.execute(
            """
            INSERT INTO companies (ticker, cik, name)
            VALUES ('DEMO', NULL, 'DEMO Corp')
            ON CONFLICT (ticker) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
        ).fetchone()
        company_id = row[0]

        # Resolve filing_type_id — seeded by migration.
        row = conn.execute(
            "SELECT id FROM filing_types WHERE code = '10-K'",
        ).fetchone()
        filing_type_id = row[0]

        # Upsert document — idempotent via ON CONFLICT.
        row = conn.execute(
            """
            INSERT INTO documents (company_id, filing_type_id, period, accession)
            VALUES (%s, %s, %s, 'demo-accession-0001')
            ON CONFLICT (accession) DO UPDATE SET
                company_id     = EXCLUDED.company_id,
                filing_type_id = EXCLUDED.filing_type_id,
                period         = EXCLUDED.period
            RETURNING id
            """,
            (company_id, filing_type_id, datetime.date(2024, 12, 31)),
        ).fetchone()
        doc_id = row[0]

        # Delete existing chunks for this document to stay idempotent.
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

        for idx, (text, embedding) in enumerate(zip(CHUNKS, embeddings, strict=True)):
            conn.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, tokens, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (doc_id, idx, text, len(text.split()), embedding),
            )

        conn.commit()
    print(f"Seeded document id={doc_id} with {len(CHUNKS)} chunks (ticker=DEMO, period=2024-12-31)")


if __name__ == "__main__":
    seed()
