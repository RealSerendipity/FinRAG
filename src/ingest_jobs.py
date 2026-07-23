"""Persistence helpers for durable ingest-job batches."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from src import db

ACTIVE_STATUSES = frozenset({"queued", "running", "retrying"})
TERMINAL_STATUSES = frozenset({"done", "error"})

_ROW_COLUMNS = (
    "id",
    "batch_id",
    "ticker",
    "form_type",
    "year",
    "period",
    "status",
    "attempts",
    "qstash_message_id",
    "chunks",
    "elapsed_s",
    "error_code",
    "error_message",
)


def _as_dict(row) -> dict:
    if isinstance(row, dict):
        return dict(row)
    return dict(zip(_ROW_COLUMNS, row, strict=True))


def aggregate_batch(batch_id: str, rows: Iterable) -> dict:
    """Return the public status and results for one persisted batch."""
    items = [_as_dict(row) for row in rows]
    statuses = {item["status"] for item in items}
    if items and statuses == {"done"}:
        batch_status = "done"
    elif "running" in statuses:
        batch_status = "running"
    elif statuses & {"queued", "retrying"}:
        batch_status = "queued"
    else:
        batch_status = "error"

    results = []
    for item in items:
        if item["status"] == "done":
            results.append(
                {
                    "ticker": item["ticker"],
                    "chunks": item["chunks"],
                    "elapsed_s": item["elapsed_s"],
                }
            )
        elif item["status"] == "error":
            results.append(
                {
                    "ticker": item["ticker"],
                    "error": item["error_message"],
                    "elapsed_s": item["elapsed_s"],
                }
            )

    return {
        "job_id": str(batch_id),
        "status": batch_status,
        "items": [
            {
                "id": str(item["id"]),
                "ticker": item["ticker"],
                "status": item["status"],
                "attempts": item["attempts"],
            }
            for item in items
        ],
        "results": results,
    }


def create_batch(
    tickers: list[str],
    *,
    form_type: str,
    year: int | None,
    period: str | None,
) -> tuple[str, list[str]]:
    """Create one queued ingest item for every ticker in a new batch."""
    batch_id = str(uuid.uuid4())
    item_ids = [str(uuid.uuid4()) for _ in tickers]
    rows = [
        (item_id, batch_id, ticker, form_type, year, period)
        for item_id, ticker in zip(item_ids, tickers, strict=True)
    ]

    def _write(conn) -> None:
        conn.executemany(
            """
            INSERT INTO ingest_jobs
                (id, batch_id, ticker, form_type, year, period)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
            """,
            rows,
        )

    db.run_write(_write)
    return batch_id, item_ids


def get_batch(batch_id: str) -> dict | None:
    """Return the aggregated public state for a persisted batch, if it exists."""
    rows = db.query(
        """
        SELECT id::text, batch_id::text, ticker, form_type, year, period,
               status, attempts, qstash_message_id, chunks, elapsed_s,
               error_code, error_message
        FROM ingest_jobs
        WHERE batch_id = %s::uuid
        ORDER BY created_at, ticker
        """,
        (batch_id,),
    )
    return aggregate_batch(batch_id, rows) if rows else None


def get_item(item_id: str) -> dict | None:
    """Return one persisted ingest item, if it exists."""
    rows = db.query(
        """
        SELECT id::text, batch_id::text, ticker, form_type, year, period,
               status, attempts, qstash_message_id, chunks, elapsed_s,
               error_code, error_message
        FROM ingest_jobs
        WHERE id = %s::uuid
        """,
        (item_id,),
    )
    return _as_dict(rows[0]) if rows else None


def claim(item_id: str) -> dict | None:
    """Atomically claim a queued, retrying, or stale running ingest item."""
    def _write(conn) -> dict | None:
        row = conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'running',
                attempts = attempts + 1,
                started_at = COALESCE(started_at, now()),
                updated_at = now(),
                error_code = NULL,
                error_message = NULL
            WHERE id = %s::uuid
              AND (
                  status IN ('queued', 'retrying')
                  OR (
                      status = 'running'
                      AND updated_at < now() - interval '330 seconds'
                  )
              )
            RETURNING id::text, batch_id::text, ticker, form_type, year, period,
                      status, attempts, qstash_message_id, chunks, elapsed_s,
                      error_code, error_message
            """,
            (item_id,),
        ).fetchone()
        return _as_dict(row) if row else None

    return db.run_write(_write)


def record_message(item_id: str, message_id: str) -> None:
    """Store the QStash message identifier for an ingest item."""
    def _write(conn) -> None:
        conn.execute(
            """
            UPDATE ingest_jobs
            SET qstash_message_id = %s, updated_at = now()
            WHERE id = %s::uuid
            """,
            (message_id, item_id),
        )

    db.run_write(_write)


def mark_done(item_id: str, *, chunks: int, elapsed_s: float) -> None:
    """Mark an ingest item successfully completed with its result details."""
    def _write(conn) -> None:
        conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'done', chunks = %s, elapsed_s = %s,
                error_code = NULL, error_message = NULL,
                updated_at = now(), finished_at = now()
            WHERE id = %s::uuid
            """,
            (chunks, elapsed_s, item_id),
        )

    db.run_write(_write)


def mark_retrying(item_id: str, *, elapsed_s: float) -> None:
    """Mark an ingest item retryable after a transient execution failure."""
    def _write(conn) -> None:
        conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'retrying', elapsed_s = %s, updated_at = now()
            WHERE id = %s::uuid
            """,
            (elapsed_s, item_id),
        )

    db.run_write(_write)


def mark_error(
    item_id: str,
    *,
    code: str,
    message: str,
    elapsed_s: float | None = None,
) -> None:
    """Mark an ingest item terminally failed with a safe error message."""
    def _write(conn) -> None:
        conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'error', error_code = %s, error_message = %s,
                elapsed_s = COALESCE(%s, elapsed_s),
                updated_at = now(), finished_at = now()
            WHERE id = %s::uuid
            """,
            (code, message, elapsed_s, item_id),
        )

    db.run_write(_write)
