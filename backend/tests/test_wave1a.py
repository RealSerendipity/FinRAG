"""Wave 1a smoke tests: schema bootstrap + NVIDIA embedding."""

from __future__ import annotations

import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest

import src.config  # noqa: F401  # triggers load_dotenv() before any skip check


def _skip_unless(env_var: str) -> None:
    if not os.environ.get(env_var):
        pytest.skip(f"{env_var} not set")


def _database_url_with_search_path(database_url: str, schema: str) -> str:
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit(parts._replace(query=urlencode(query)))


def test_bootstrap_idempotent() -> None:
    _skip_unless("DATABASE_URL")
    from src.db import bootstrap
    bootstrap()
    bootstrap()  # second run must not raise


def test_embed_returns_1024d_vector() -> None:
    _skip_unless("NVIDIA_API_KEY")
    from src.embed import embed
    vecs = embed(["hello world"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 1024


def test_embed_multiple_texts() -> None:
    _skip_unless("NVIDIA_API_KEY")
    from src.embed import embed
    vecs = embed(["first sentence", "second sentence"])
    assert len(vecs) == 2
    assert all(len(v) == 1024 for v in vecs)


def test_embed_empty_returns_empty() -> None:
    from src.embed import embed
    assert embed([]) == []


def test_ingest_audit_timestamps_only_mark_real_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_unless("DATABASE_URL")

    from src import db, ingest

    original_database_url = db.config.database_url
    base_database_url = original_database_url()
    schema = f"audit_{uuid.uuid4().hex}"
    ticker = f"T{uuid.uuid4().hex[:8]}".upper()
    accession = f"audit-{uuid.uuid4().hex}"
    company_name = "Audit Test Corp"
    raw_url = "https://example.test/filing-v1"

    def fake_company_info_for_ticker(_: str) -> dict[str, object]:
        return {"cik": 1234567890, "name": company_name}

    def fake_fetch_filing(_: str, __: str, ___: str) -> dict[str, str]:
        return {
            "report_date": "2024-12-31",
            "filed_at": "2025-01-30",
            "accession": accession,
            "raw_url": raw_url,
            "text": "Revenue increased.\n\nOperating margin expanded.",
        }

    def fake_embed_batched(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(ingest, "company_info_for_ticker", fake_company_info_for_ticker)
    monkeypatch.setattr(ingest, "fetch_filing", fake_fetch_filing)
    monkeypatch.setattr(ingest, "_embed_batched", fake_embed_batched)
    with db.get_conn() as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.commit()
    monkeypatch.setattr(
        db.config,
        "database_url",
        lambda: _database_url_with_search_path(base_database_url, schema),
    )

    try:
        db.bootstrap()
        with db.get_conn() as conn:
            audit_columns = conn.execute(
                """
                SELECT table_name, column_default
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name IN ('companies', 'filing_types', 'documents', 'chunks')
                  AND column_name = 'updated_at'
                ORDER BY table_name
                """,
                (schema,),
            ).fetchall()
            audit_triggers = conn.execute(
                """
                SELECT event_object_table, trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = %s
                  AND event_object_table IN ('companies', 'filing_types', 'documents', 'chunks')
                ORDER BY event_object_table, trigger_name
                """,
                (schema,),
            ).fetchall()

        assert audit_columns == [
            ("chunks", None),
            ("companies", None),
            ("documents", None),
            ("filing_types", None),
        ]
        assert audit_triggers == [
            ("chunks", "chunks_updated_at"),
            ("companies", "companies_updated_at"),
            ("documents", "documents_updated_at"),
            ("filing_types", "filing_types_updated_at"),
        ]

        ingest.ingest(ticker, fiscal_year=2024)

        with db.get_conn() as conn:
            first = conn.execute(
                """
                SELECT c.created_at, c.updated_at,
                       d.created_at, d.updated_at,
                       count(ch.id) FILTER (
                           WHERE ch.created_at IS NOT NULL AND ch.updated_at IS NULL
                       )
                FROM companies c
                JOIN documents d ON d.company_id = c.id
                JOIN chunks ch ON ch.document_id = d.id
                WHERE c.ticker = %s AND d.accession = %s
                GROUP BY c.created_at, c.updated_at, d.created_at, d.updated_at
                """,
                (ticker, accession),
            ).fetchone()

        assert first is not None
        (
            company_created_at,
            company_updated_at,
            document_created_at,
            document_updated_at,
            clean_chunks,
        ) = first
        assert company_created_at is not None
        assert company_updated_at is None
        assert document_created_at is not None
        assert document_updated_at is None
        assert clean_chunks > 0

        ingest.ingest(ticker, fiscal_year=2024)

        with db.get_conn() as conn:
            second = conn.execute(
                """
                SELECT c.created_at, c.updated_at, d.created_at, d.updated_at
                FROM companies c
                JOIN documents d ON d.company_id = c.id
                WHERE c.ticker = %s AND d.accession = %s
                """,
                (ticker, accession),
            ).fetchone()

        assert second == (company_created_at, None, document_created_at, None)

        company_name = "Audit Test Corp Renamed"
        raw_url = "https://example.test/filing-v2"
        ingest.ingest(ticker, fiscal_year=2024)

        with db.get_conn() as conn:
            third = conn.execute(
                """
                SELECT c.created_at, c.updated_at, d.created_at, d.updated_at
                FROM companies c
                JOIN documents d ON d.company_id = c.id
                WHERE c.ticker = %s AND d.accession = %s
                """,
                (ticker, accession),
            ).fetchone()

        assert third is not None
        assert third[0] == company_created_at
        assert third[1] is not None
        assert third[2] == document_created_at
        assert third[3] is not None
    finally:
        monkeypatch.setattr(db.config, "database_url", original_database_url)
        with db.get_conn() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.commit()
