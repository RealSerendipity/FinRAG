"""Database connection and schema bootstrap.

Public surface
--------------
- `get_conn()` — returns a psycopg connection (autocommit off)
- `bootstrap()` — runs sql/001_init.sql idempotently; safe to call on every startup
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from . import config

_SQL_DIR = Path(__file__).parent.parent / "sql"


def get_conn() -> psycopg.Connection:
    url = config.database_url()
    return psycopg.connect(url)


def bootstrap() -> None:
    """Apply all sql/*.sql migrations in filename order. Idempotent."""
    migrations = sorted(_SQL_DIR.glob("*.sql"))
    with get_conn() as conn:
        for path in migrations:
            conn.execute(path.read_text())
        conn.commit()
