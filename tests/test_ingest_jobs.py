"""Offline tests for persisted ingest-job state."""

from __future__ import annotations

from src import ingest_jobs


def _row(ticker: str, status: str, **extra):
    return {
        "id": f"id-{ticker}",
        "batch_id": "batch-1",
        "ticker": ticker,
        "form_type": "10-K",
        "year": 2024,
        "period": None,
        "status": status,
        "attempts": extra.get("attempts", 0),
        "chunks": extra.get("chunks"),
        "elapsed_s": extra.get("elapsed_s"),
        "error_code": extra.get("error_code"),
        "error_message": extra.get("error_message"),
    }


def test_aggregate_batch_done_only_when_every_item_is_done():
    body = ingest_jobs.aggregate_batch(
        "batch-1",
        [_row("AAPL", "done", chunks=42), _row("MSFT", "done", chunks=35)],
    )

    assert body["status"] == "done"
    assert body["results"] == [
        {"ticker": "AAPL", "chunks": 42, "elapsed_s": None},
        {"ticker": "MSFT", "chunks": 35, "elapsed_s": None},
    ]


def test_aggregate_batch_running_wins_and_retrying_is_queued():
    running = ingest_jobs.aggregate_batch(
        "batch-1", [_row("AAPL", "done"), _row("MSFT", "running", attempts=1)]
    )
    queued = ingest_jobs.aggregate_batch(
        "batch-1", [_row("AAPL", "done"), _row("MSFT", "retrying", attempts=2)]
    )

    assert running["status"] == "running"
    assert queued["status"] == "queued"


def test_aggregate_batch_errors_when_no_active_items_remain():
    body = ingest_jobs.aggregate_batch(
        "batch-1",
        [
            _row("AAPL", "done", chunks=42),
            _row(
                "ZZZZ",
                "error",
                error_code="invalid_request",
                error_message="no filing found",
            ),
        ],
    )

    assert body["status"] == "error"
    assert body["results"][1] == {
        "ticker": "ZZZZ",
        "error": "no filing found",
        "elapsed_s": None,
    }


def test_get_batch_returns_none_for_an_unknown_batch(monkeypatch):
    monkeypatch.setattr(ingest_jobs.db, "query", lambda sql, params: [])

    assert ingest_jobs.get_batch("missing") is None


def test_create_batch_inserts_one_row_per_ticker_in_one_executemany(monkeypatch):
    calls = []

    class _Conn:
        def executemany(self, sql, params):
            calls.append((sql, list(params)))

    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(_Conn()))

    batch_id, item_ids = ingest_jobs.create_batch(
        ["AAPL", "MSFT"], form_type="10-K", year=2024, period=None
    )

    assert len(item_ids) == 2
    assert len(calls) == 1
    assert calls[0][1][0][1] == batch_id
    assert [row[2] for row in calls[0][1]] == ["AAPL", "MSFT"]


def test_get_batch_maps_persisted_tuple_rows_and_aggregates(monkeypatch):
    monkeypatch.setattr(
        ingest_jobs.db,
        "query",
        lambda sql, params: [
            (
                "item-1",
                "batch-1",
                "AAPL",
                "10-K",
                2024,
                None,
                "done",
                1,
                "msg-1",
                42,
                3.2,
                None,
                None,
            )
        ],
    )

    body = ingest_jobs.get_batch("batch-1")

    assert body == {
        "job_id": "batch-1",
        "status": "done",
        "items": [{"id": "item-1", "ticker": "AAPL", "status": "done", "attempts": 1}],
        "results": [{"ticker": "AAPL", "chunks": 42, "elapsed_s": 3.2}],
    }


def test_get_item_maps_a_row_and_returns_none_when_absent(monkeypatch):
    row = (
        "item-1",
        "batch-1",
        "AAPL",
        "10-K",
        2024,
        None,
        "queued",
        0,
        None,
        None,
        None,
        None,
        None,
    )
    monkeypatch.setattr(ingest_jobs.db, "query", lambda sql, params: [row])

    assert ingest_jobs.get_item("item-1") == {
        "id": "item-1",
        "batch_id": "batch-1",
        "ticker": "AAPL",
        "form_type": "10-K",
        "year": 2024,
        "period": None,
        "status": "queued",
        "attempts": 0,
        "qstash_message_id": None,
        "chunks": None,
        "elapsed_s": None,
        "error_code": None,
        "error_message": None,
    }

    monkeypatch.setattr(ingest_jobs.db, "query", lambda sql, params: [])
    assert ingest_jobs.get_item("missing") is None


def test_claim_recovers_stale_running_rows_and_increments_attempts(monkeypatch):
    calls = []

    class _Result:
        def fetchone(self):
            return (
                "item-1",
                "batch-1",
                "AAPL",
                "10-K",
                2024,
                None,
                "running",
                2,
                None,
                None,
                None,
                None,
                None,
            )

    class _Conn:
        def execute(self, sql, params):
            calls.append((sql, params))
            return _Result()

    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(_Conn()))

    claimed = ingest_jobs.claim("item-1")

    assert claimed["status"] == "running"
    assert claimed["attempts"] == 2
    assert "attempts = attempts + 1" in calls[0][0]
    assert "interval '330 seconds'" in calls[0][0]
    assert "COALESCE(started_at, now())" in calls[0][0]
    assert calls[0][1] == ("item-1",)


def test_state_transitions_issue_expected_status_updates(monkeypatch):
    calls = []

    class _Conn:
        def execute(self, sql, params):
            calls.append((sql, params))

    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(_Conn()))

    ingest_jobs.record_message("item-1", "message-1")
    ingest_jobs.mark_done("item-1", chunks=42, elapsed_s=3.2)
    ingest_jobs.mark_retrying("item-1", elapsed_s=1.5)
    ingest_jobs.mark_error(
        "item-1", code="invalid_request", message="no filing found", elapsed_s=1.5
    )

    assert "qstash_message_id = %s" in calls[0][0]
    assert calls[0][1] == ("message-1", "item-1")
    assert "status = 'done'" in calls[1][0]
    assert "finished_at = now()" in calls[1][0]
    assert calls[1][1] == (42, 3.2, "item-1")
    assert "status = 'retrying'" in calls[2][0]
    assert calls[2][1] == (1.5, "item-1")
    assert "status = 'error'" in calls[3][0]
    assert "finished_at = now()" in calls[3][0]
    assert calls[3][1] == ("invalid_request", "no filing found", 1.5, "item-1")
