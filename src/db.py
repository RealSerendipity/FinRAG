"""Database connection and schema bootstrap.

Public surface
--------------
- `get_conn()` — context manager yielding a pooled psycopg connection
- `bootstrap()` — runs sql/001_init.sql idempotently; safe to call on every startup

A cold Neon (free-tier) connect costs ~5s and Neon drops idle connections
server-side, so opening a connection per query turns a sub-second query into a
~30s one and makes an ablation sweep unusable. The workload here is
single-threaded (CLI + eval), so we keep one process-wide connection alive and
reuse it. The connection runs in autocommit mode: Neon also enforces an
idle-in-transaction timeout, and a long CPU/HTTP gap (e.g. embedding hundreds of
chunks) between two statements of the same implicit transaction would otherwise
get the connection killed. Callers needing multi-statement atomicity open an
explicit `with conn.transaction():` block. A genuinely dropped connection is
detected and re-established on the next call. (A concurrent server path, Wave 5,
should move to a real pool.)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import psycopg

from . import config

_SQL_DIR = Path(__file__).parent.parent / "sql"

_conn: psycopg.Connection | None = None
_conn_url: str | None = None

# Neon free-tier drops idle connections server-side and suspends idle compute.
# A dropped TCP socket the client hasn't noticed makes the next query block
# forever (half-open socket), so: enable TCP keepalives to detect death fast,
# cap any single statement, and bound the connect itself.
_CONNECT_KWARGS = {
    "connect_timeout": 15,
    "keepalives": 1,
    "keepalives_idle": 20,
    "keepalives_interval": 5,
    "keepalives_count": 3,
}


def _connect(url: str) -> psycopg.Connection:
    # NB: don't pass libpq `options=` here — it would override any options already
    # in the DSN (e.g. a search_path used by tests). Set the statement timeout with
    # a SET after connecting instead (autocommit makes it take effect immediately).
    conn = psycopg.connect(url, autocommit=True, **_CONNECT_KWARGS)
    conn.execute("SET statement_timeout = 45000")
    return conn


def _live_conn() -> psycopg.Connection:
    """Return a cached connection, reconnecting if absent/closed/broken or dead.

    A cheap `SELECT 1` ping detects a server-side-dropped connection (warm ping
    is sub-millisecond); on failure we discard and reconnect rather than letting
    a later real query hang on a stale socket.
    """
    global _conn, _conn_url
    url = config.database_url()
    if _conn is not None and (_conn.closed or _conn.broken or _conn_url != url):
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
        except Exception:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
    if _conn is None:
        _conn = _connect(url)
        _conn_url = url
    return _conn


def _reset() -> None:
    """Drop the cached connection so the next call reconnects."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


@contextmanager
def get_conn():
    """Yield the reused autocommit connection (kept open across calls).

    Statements autocommit individually. For multi-statement atomicity, open an
    explicit `with conn.transaction():` block inside the with-body.
    """
    yield _live_conn()


def query(sql: str, params=None, *, retries: int = 3) -> list:
    """Run a read query and return fetchall(), retrying transient DB failures.

    Neon free-tier intermittently drops the connection mid-query (SSL "bad record
    mac", server-closed, operational errors). A single retrieval shouldn't crash a
    long eval run over a blip, so we drop the connection and reconnect on such
    errors with exponential back-off. Not used for writes (those need a transaction).
    """
    delay = 0.5
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return _live_conn().execute(sql, params).fetchall()
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            last = exc
            _reset()  # force a fresh connection on the next attempt
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last  # unreachable; satisfies type checker


def bootstrap() -> None:
    """Apply all sql/*.sql migrations in filename order. Idempotent."""
    migrations = sorted(_SQL_DIR.glob("*.sql"))
    with get_conn() as conn, conn.transaction():
        for path in migrations:
            conn.execute(path.read_text())
