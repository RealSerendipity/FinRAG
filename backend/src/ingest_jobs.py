"""Persistence helpers for durable ingest-job batches."""

from __future__ import annotations

import hashlib
import json
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
    "claim_token",
    "qstash_message_id",
    "chunks",
    "elapsed_s",
    "error_code",
    "error_message",
)


class IdempotencyConflictError(ValueError):
    """Signal reuse of an idempotency key for a different ingest request."""


def _as_dict(row) -> dict:
    if isinstance(row, dict):
        return dict(row)
    return dict(zip(_ROW_COLUMNS, row, strict=True))


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _is_replayed_transition(
    conn,
    *,
    item_id: str,
    claim_token: str,
    status: str,
    expected: dict[str, object],
) -> bool:
    row = conn.execute(
        """
        SELECT status, claim_token::text, chunks, elapsed_s, error_code, error_message
        FROM ingest_jobs
        WHERE id = %s::uuid
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        return False
    current = dict(
        zip(
            ("status", "claim_token", "chunks", "elapsed_s", "error_code", "error_message"),
            row,
            strict=True,
        )
    )
    return (
        current["status"] == status
        and current["claim_token"] == claim_token
        and all(current[field] == value for field, value in expected.items())
    )


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
    idempotency_key: str,
) -> tuple[str, list[str]]:
    """Create or replay one durable batch identified by an idempotency key."""
    candidate_batch_id = str(uuid.uuid4())
    canonical_request = json.dumps(
        {
            "tickers": tickers,
            "form_type": form_type,
            "year": year,
            "period": period,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(canonical_request.encode()).hexdigest()

    def _write(conn) -> tuple[str, list[str]]:
        batch_row = conn.execute(
            """
            INSERT INTO ingest_batches (id, idempotency_key, request_fingerprint)
            VALUES (%s::uuid, %s, %s)
            ON CONFLICT (idempotency_key) DO UPDATE
            SET idempotency_key = EXCLUDED.idempotency_key
            RETURNING id::text, request_fingerprint
            """,
            (candidate_batch_id, idempotency_key, fingerprint),
        ).fetchone()
        batch_id, persisted_fingerprint = batch_row
        if persisted_fingerprint != fingerprint:
            raise IdempotencyConflictError

        batch_uuid = uuid.UUID(batch_id)
        item_ids = [
            str(uuid.uuid5(batch_uuid, f"ingest-item:{index}"))
            for index in range(len(tickers))
        ]
        rows = [
            (item_id, batch_id, ticker, form_type, year, period)
            for item_id, ticker in zip(item_ids, tickers, strict=True)
        ]
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO ingest_jobs
                    (id, batch_id, ticker, form_type, year, period)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                rows,
            )
        return batch_id, item_ids

    return db.run_write(_write)


def get_batch(batch_id: str) -> dict | None:
    """Return the aggregated public state for a persisted batch, if it exists."""
    if not _is_valid_uuid(batch_id):
        return None
    rows = db.query(
        """
        SELECT id::text, batch_id::text, ticker, form_type, year, period,
               status, attempts, claim_token::text, qstash_message_id, chunks, elapsed_s,
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
    if not _is_valid_uuid(item_id):
        return None
    rows = db.query(
        """
        SELECT id::text, batch_id::text, ticker, form_type, year, period,
               status, attempts, claim_token::text, qstash_message_id, chunks, elapsed_s,
               error_code, error_message
        FROM ingest_jobs
        WHERE id = %s::uuid
        """,
        (item_id,),
    )
    return _as_dict(rows[0]) if rows else None


def claim(item_id: str) -> dict | None:
    """Atomically claim a queued, retrying, or stale running item with a token."""
    if not _is_valid_uuid(item_id):
        return None
    claim_token = str(uuid.uuid4())

    def _write(conn) -> dict | None:
        row = conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'running',
                attempts = CASE
                    WHEN claim_token IS DISTINCT FROM %s::uuid THEN attempts + 1
                    ELSE attempts
                END,
                claim_token = %s::uuid,
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
                  OR (
                      status = 'running'
                      AND claim_token = %s::uuid
                  )
              )
            RETURNING id::text, batch_id::text, ticker, form_type, year, period,
                      status, attempts, claim_token::text, qstash_message_id, chunks, elapsed_s,
                      error_code, error_message
            """,
            (claim_token, claim_token, item_id, claim_token),
        ).fetchone()
        return _as_dict(row) if row else None

    return db.run_write(_write)


def record_message(item_id: str, message_id: str) -> bool:
    """Store a QStash message ID and report whether its item exists."""
    if not _is_valid_uuid(item_id):
        return False

    def _write(conn) -> bool:
        result = conn.execute(
            """
            UPDATE ingest_jobs
            SET qstash_message_id = %s, updated_at = now()
            WHERE id = %s::uuid
            """,
            (message_id, item_id),
        )
        return result.rowcount == 1

    return db.run_write(_write)


def mark_done(item_id: str, *, claim_token: str, chunks: int, elapsed_s: float) -> bool:
    """Mark a token-owned running item done, returning whether it was accepted."""
    if not _is_valid_uuid(item_id) or not _is_valid_uuid(claim_token):
        return False

    def _write(conn) -> bool:
        result = conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'done', chunks = %s, elapsed_s = %s,
                error_code = NULL, error_message = NULL,
                updated_at = now(), finished_at = now()
            WHERE id = %s::uuid
              AND status = 'running'
              AND claim_token = %s::uuid
            """,
            (chunks, elapsed_s, item_id, claim_token),
        )
        if result.rowcount == 1:
            return True
        return _is_replayed_transition(
            conn,
            item_id=item_id,
            claim_token=claim_token,
            status="done",
            expected={"chunks": chunks, "elapsed_s": elapsed_s},
        )

    return db.run_write(_write)


def mark_retrying(item_id: str, *, claim_token: str, elapsed_s: float) -> bool:
    """Mark a token-owned running item retryable, returning whether it was accepted."""
    if not _is_valid_uuid(item_id) or not _is_valid_uuid(claim_token):
        return False

    def _write(conn) -> bool:
        result = conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'retrying', elapsed_s = %s, updated_at = now()
            WHERE id = %s::uuid
              AND status = 'running'
              AND claim_token = %s::uuid
            """,
            (elapsed_s, item_id, claim_token),
        )
        if result.rowcount == 1:
            return True
        return _is_replayed_transition(
            conn,
            item_id=item_id,
            claim_token=claim_token,
            status="retrying",
            expected={"elapsed_s": elapsed_s},
        )

    return db.run_write(_write)


def mark_error(
    item_id: str,
    *,
    code: str,
    message: str,
    elapsed_s: float | None = None,
    claim_token: str | None = None,
) -> bool:
    """Fence worker errors by token; no-token delivery errors never overwrite done."""
    if not _is_valid_uuid(item_id) or (
        claim_token is not None and not _is_valid_uuid(claim_token)
    ):
        return False

    if claim_token is None:
        def _write(conn) -> bool:
            result = conn.execute(
                """
                UPDATE ingest_jobs
                SET status = 'error', error_code = %s, error_message = %s,
                    elapsed_s = COALESCE(%s, elapsed_s),
                    updated_at = now(), finished_at = now()
                WHERE id = %s::uuid
                  AND status <> 'done'
                """,
                (code, message, elapsed_s, item_id),
            )
            return result.rowcount == 1

        return db.run_write(_write)

    def _write(conn) -> bool:
        result = conn.execute(
            """
            UPDATE ingest_jobs
            SET status = 'error', error_code = %s, error_message = %s,
                elapsed_s = COALESCE(%s, elapsed_s),
                updated_at = now(), finished_at = now()
            WHERE id = %s::uuid
              AND status = 'running'
              AND claim_token = %s::uuid
            """,
            (code, message, elapsed_s, item_id, claim_token),
        )
        if result.rowcount == 1:
            return True
        expected = {"error_code": code, "error_message": message}
        if elapsed_s is not None:
            expected["elapsed_s"] = elapsed_s
        return _is_replayed_transition(
            conn,
            item_id=item_id,
            claim_token=claim_token,
            status="error",
            expected=expected,
        )

    return db.run_write(_write)
