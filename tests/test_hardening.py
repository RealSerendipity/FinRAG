"""P0/P1 hardening tests — connection pooling (db.py) and filtered-retrieval
recall observability (retrieve.py). Network-free: the pool class and the search
functions are faked.
"""

from __future__ import annotations

import contextlib
import logging

import psycopg
import pytest

from src import db


# --------------------------------------------------------------------------- #
# db._configure — session setup applied to every pooled connection
# --------------------------------------------------------------------------- #
class _FakeConn:
    def __init__(self, fail_on: str | None = None):
        self.autocommit = False
        self.executed: list[str] = []
        self._fail_on = fail_on

    def execute(self, sql, params=None):
        if self._fail_on and self._fail_on in sql:
            raise psycopg.errors.UndefinedObject("unrecognized configuration parameter")
        self.executed.append(sql)
        return self


def test_configure_sets_autocommit_and_timeout():
    conn = _FakeConn()
    db._configure(conn)
    assert conn.autocommit is True
    assert any("statement_timeout" in s for s in conn.executed)


def test_configure_enables_iterative_scan_when_available():
    # pgvector >= 0.8: iterative index scans keep filtered HNSW queries from
    # starving (post-filter recall loss).
    conn = _FakeConn()
    db._configure(conn)
    assert any("hnsw.iterative_scan" in s for s in conn.executed)


def test_configure_survives_older_pgvector():
    # pgvector < 0.8 rejects the GUC — _configure must swallow that, not raise.
    conn = _FakeConn(fail_on="hnsw.iterative_scan")
    db._configure(conn)
    assert conn.autocommit is True


# --------------------------------------------------------------------------- #
# db._get_pool — one pool per DATABASE_URL, recreated when the URL changes
# --------------------------------------------------------------------------- #
class _FakePool:
    instances: list[_FakePool] = []

    @staticmethod
    def check_connection(conn):  # mirrors ConnectionPool.check_connection
        pass

    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.opened = False
        self.closed = False
        _FakePool.instances.append(self)

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_pool(monkeypatch):
    _FakePool.instances = []
    monkeypatch.setattr(db, "ConnectionPool", _FakePool)
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_pool_url", None)
    return _FakePool


def test_get_pool_is_singleton_per_url(fake_pool, monkeypatch):
    monkeypatch.setattr(db.config, "database_url", lambda: "postgresql://u@h1/db")
    p1 = db._get_pool()
    p2 = db._get_pool()
    assert p1 is p2
    assert p1.opened
    assert len(fake_pool.instances) == 1
    # The Neon keepalive/timeout kwargs must reach the pooled connections.
    assert p1.kwargs["kwargs"] == db._CONNECT_KWARGS


def test_get_pool_recreates_on_url_change(fake_pool, monkeypatch):
    urls = iter(["postgresql://u@h1/db", "postgresql://u@h2/db"])
    current = {"url": next(urls)}
    monkeypatch.setattr(db.config, "database_url", lambda: current["url"])
    p1 = db._get_pool()
    current["url"] = next(urls)
    p2 = db._get_pool()
    assert p2 is not p1
    assert p1.closed


# --------------------------------------------------------------------------- #
# db.query — retries transient failures on a fresh pooled connection
# --------------------------------------------------------------------------- #
def test_query_retries_transient_failures(monkeypatch):
    calls = {"n": 0}

    class _Cursorish:
        def fetchall(self):
            return [("ok",)]

    class _Conn:
        def execute(self, sql, params=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise psycopg.OperationalError("SSL error: bad record mac")
            return _Cursorish()

    @contextlib.contextmanager
    def fake_get_conn():
        yield _Conn()

    monkeypatch.setattr(db, "get_conn", fake_get_conn)
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    assert db.query("SELECT 1") == [("ok",)]
    assert calls["n"] == 3


def test_query_raises_after_exhausted_retries(monkeypatch):
    class _Conn:
        def execute(self, sql, params=None):
            raise psycopg.OperationalError("dead")

    @contextlib.contextmanager
    def fake_get_conn():
        yield _Conn()

    monkeypatch.setattr(db, "get_conn", fake_get_conn)
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    with pytest.raises(psycopg.OperationalError):
        db.query("SELECT 1", retries=2)


# --------------------------------------------------------------------------- #
# ingest — concurrent ingests of the same filing must serialize on an advisory
# lock (DELETE+INSERT chunk replacement would otherwise interleave)
# --------------------------------------------------------------------------- #
def test_ingest_takes_advisory_lock_on_accession(monkeypatch):
    from src import ingest

    executed: list[tuple[str, tuple]] = []

    class _FakeCursor:
        def fetchone(self):
            return (1,)

    class _FakeIngestConn:
        @contextlib.contextmanager
        def transaction(self):
            yield

        def execute(self, sql, params=None):
            executed.append((" ".join(sql.split()), params or ()))
            return _FakeCursor()

    @contextlib.contextmanager
    def fake_get_conn():
        yield _FakeIngestConn()

    monkeypatch.setattr(ingest, "get_conn", fake_get_conn)
    monkeypatch.setattr(
        ingest, "company_info_for_ticker", lambda t: {"cik": 123, "name": "Test Corp"}
    )
    monkeypatch.setattr(
        ingest, "fetch_filing",
        lambda t, f, p: {
            "accession": "acc-0001",
            "filed_at": "2025-01-30",
            "report_date": "2024-12-31",
            "raw_url": "https://example.test/f",
            "text": "Revenue increased.\n\nOperating margin expanded.",
        },
    )
    monkeypatch.setattr(
        ingest, "_embed_batched", lambda texts: [[0.0] * 4 for _ in texts]
    )
    ingest.ingest("TEST", fiscal_year=2024)
    lock_calls = [(s, p) for s, p in executed if "pg_advisory_xact_lock" in s]
    assert lock_calls, "ingest must take an advisory lock keyed by accession"
    assert lock_calls[0][1] == ("acc-0001",)
    # The lock must be taken before the document/chunks writes.
    lock_idx = next(i for i, (s, _) in enumerate(executed) if "pg_advisory_xact_lock" in s)
    chunk_idx = next(i for i, (s, _) in enumerate(executed) if "INSERT INTO chunks" in s)
    assert lock_idx < chunk_idx


# --------------------------------------------------------------------------- #
# retrieve — warn when a filtered vector search returns fewer than requested
# (HNSW post-filtering starvation is silent otherwise)
# --------------------------------------------------------------------------- #
def test_retrieve_warns_on_filtered_shortfall(monkeypatch, caplog):
    from src import retrieve as r

    monkeypatch.setattr(r, "embed", lambda texts, **k: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(
        r.db, "query",
        lambda sql, params=None, **k: [(1, "content", None, 0, {}, 0.1)],
    )
    with caplog.at_level(logging.WARNING, logger="src.retrieve"):
        out = r.retrieve(
            "revenue", ticker="AAPL", top_k=5, mode="dense", rerank=False, rewrite="none"
        )
    assert len(out) == 1
    assert "post-filter" in caplog.text


def test_retrieve_no_warning_without_filters(monkeypatch, caplog):
    from src import retrieve as r

    monkeypatch.setattr(r, "embed", lambda texts, **k: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(
        r.db, "query",
        lambda sql, params=None, **k: [(1, "content", None, 0, {}, 0.1)],
    )
    with caplog.at_level(logging.WARNING, logger="src.retrieve"):
        r.retrieve("revenue", top_k=5, mode="dense", rerank=False, rewrite="none")
    assert "post-filter" not in caplog.text
