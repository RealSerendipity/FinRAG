"""Database connection pool and schema bootstrap.

Public surface
--------------
- `get_conn()` — context manager yielding a pooled psycopg connection
- `query(sql, params)` — read query with retry on transient Neon failures
- `bootstrap()` — runs sql/*.sql idempotently; safe to call on every startup

A cold Neon (free-tier) connect costs ~5s and Neon drops idle connections
server-side, so opening a connection per query is unusable. Wave 5 put a
concurrent FastAPI surface (thread pool) in front of this module, so the old
process-wide single connection became both a serialization bottleneck and a
race (two threads could reconnect/close each other's connection). We now use a
`psycopg_pool.ConnectionPool`:

- `min_size=1` keeps one warm connection (Neon cold-connect paid once);
- `check=check_connection` pings at checkout, replacing the old manual ping, so
  a server-side-dropped connection is discarded instead of hanging a query;
- every connection is configured in autocommit with a statement timeout (Neon
  also enforces an idle-in-transaction timeout; long CPU/HTTP gaps between two
  statements of an implicit transaction would get the connection killed).

Callers needing multi-statement atomicity open an explicit
`with conn.transaction():` block inside the `get_conn()` body.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from . import config

_SQL_DIR = Path(__file__).parent.parent / "sql"

_pool: ConnectionPool | None = None
_pool_url: str | None = None
_pool_lock = threading.Lock()

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

_POOL_MAX_SIZE = 8  # bounded well under Neon free-tier connection limits


def _configure(conn: psycopg.Connection) -> None:
    """Session setup for every pooled connection.

    NB: don't pass libpq `options=` in the DSN kwargs — it would override any
    options already in the DSN (e.g. a search_path used by tests). Autocommit is
    set BEFORE the SETs so they take effect immediately instead of opening a
    transaction. `hnsw.iterative_scan` (pgvector >= 0.8) keeps filtered vector
    queries from starving under HNSW post-filtering; older pgvector rejects the
    GUC, which is tolerated (the recall mitigation is then unavailable).
    """
    conn.autocommit = True
    conn.execute("SET statement_timeout = 45000")
    try:
        conn.execute("SET hnsw.iterative_scan = 'relaxed_order'")
    except Exception:
        pass


def _get_pool() -> ConnectionPool:
    """Return the process-wide pool, (re)creating it when DATABASE_URL changes."""
    global _pool, _pool_url
    url = config.database_url()
    with _pool_lock:
        if _pool is not None and _pool_url != url:
            try:
                _pool.close()
            except Exception:
                pass
            _pool = None
        if _pool is None:
            _pool = ConnectionPool(
                url,
                min_size=1,
                max_size=_POOL_MAX_SIZE,
                kwargs=_CONNECT_KWARGS,
                configure=_configure,
                check=ConnectionPool.check_connection,
                open=False,
                name="finrag",
            )
            _pool.open()
            _pool_url = url
        return _pool


@contextmanager
def get_conn():
    """Yield a pooled autocommit connection (returned to the pool on exit).

    Statements autocommit individually. For multi-statement atomicity, open an
    explicit `with conn.transaction():` block inside the with-body.
    """
    with _get_pool().connection() as conn:
        yield conn


# Transient failure modes shared by the read and write retry paths: Neon
# free-tier drops connections mid-statement (SSL "bad record mac", server-closed)
# and a saturated pool times out at checkout.
_TRANSIENT_EXCS = (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout)


def query(sql: str, params=None, *, retries: int = 3) -> list:
    """Run a read query and return fetchall(), retrying transient DB failures.

    A single retrieval shouldn't crash a long eval run over a Neon blip, so we
    retry on a fresh pooled connection with exponential back-off (the pool
    discards a connection broken by the failure).
    """
    delay = 0.5
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with get_conn() as conn:
                return conn.execute(sql, params).fetchall()
        except _TRANSIENT_EXCS as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last  # unreachable; satisfies type checker


def run_write(fn, *, retries: int = 3):
    """Run `fn(conn)` inside one explicit transaction, retrying transient failures.

    The whole transaction re-runs on a retry, so `fn` must be idempotent —
    finrag's writes are upserts / delete-then-insert replacements, which are.
    This is the write-side counterpart of query()'s retry: an ingest has already
    paid minutes of EDGAR + embedding work by the time it writes, and that work
    (held in memory) should survive a dropped Neon connection.
    """
    delay = 0.5
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with get_conn() as conn, conn.transaction():
                return fn(conn)
        except _TRANSIENT_EXCS as exc:
            last = exc
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
