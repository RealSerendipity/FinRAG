"""Offline tests for persisted ingest-job state."""

from __future__ import annotations

import uuid

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

    assert ingest_jobs.get_batch("00000000-0000-0000-0000-000000000099") is None


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
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "AAPL",
                "10-K",
                2024,
                None,
                "done",
                1,
                None,
                "msg-1",
                42,
                3.2,
                None,
                None,
            )
        ],
    )

    body = ingest_jobs.get_batch("00000000-0000-0000-0000-000000000002")

    assert body == {
        "job_id": "00000000-0000-0000-0000-000000000002",
        "status": "done",
        "items": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "ticker": "AAPL",
                "status": "done",
                "attempts": 1,
            }
        ],
        "results": [{"ticker": "AAPL", "chunks": 42, "elapsed_s": 3.2}],
    }


def test_get_item_maps_a_row_and_returns_none_when_absent(monkeypatch):
    row = (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
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
        None,
    )
    monkeypatch.setattr(ingest_jobs.db, "query", lambda sql, params: [row])

    assert ingest_jobs.get_item("00000000-0000-0000-0000-000000000001") == {
        "id": "00000000-0000-0000-0000-000000000001",
        "batch_id": "00000000-0000-0000-0000-000000000002",
        "ticker": "AAPL",
        "form_type": "10-K",
        "year": 2024,
        "period": None,
        "status": "queued",
        "attempts": 0,
        "claim_token": None,
        "qstash_message_id": None,
        "chunks": None,
        "elapsed_s": None,
        "error_code": None,
        "error_message": None,
    }

    monkeypatch.setattr(ingest_jobs.db, "query", lambda sql, params: [])
    assert ingest_jobs.get_item("00000000-0000-0000-0000-000000000099") is None


def test_claim_recovers_stale_running_rows_and_increments_attempts(monkeypatch):
    calls = []

    class _Result:
        rowcount = 1

        def fetchone(self):
            return (
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "AAPL",
                "10-K",
                2024,
                None,
                "running",
                2,
                "00000000-0000-0000-0000-000000000003",
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

    claimed = ingest_jobs.claim("00000000-0000-0000-0000-000000000001")

    assert claimed["status"] == "running"
    assert claimed["attempts"] == 2
    assert "attempts = CASE" in calls[0][0]
    assert "interval '330 seconds'" in calls[0][0]
    assert "COALESCE(started_at, now())" in calls[0][0]
    assert calls[0][1][2] == "00000000-0000-0000-0000-000000000001"


def test_state_transitions_issue_expected_status_updates(monkeypatch):
    calls = []

    class _Conn:
        def execute(self, sql, params):
            calls.append((sql, params))
            return type("_Result", (), {"rowcount": 1})()

    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(_Conn()))

    item_id = "00000000-0000-0000-0000-000000000001"
    claim_token = "00000000-0000-0000-0000-000000000003"
    assert ingest_jobs.record_message(item_id, "message-1")
    assert ingest_jobs.mark_done(item_id, claim_token=claim_token, chunks=42, elapsed_s=3.2)
    assert ingest_jobs.mark_retrying(item_id, claim_token=claim_token, elapsed_s=1.5)
    assert ingest_jobs.mark_error(
        item_id,
        claim_token=claim_token,
        code="invalid_request",
        message="no filing found",
        elapsed_s=1.5,
    )

    assert "qstash_message_id = %s" in calls[0][0]
    assert calls[0][1] == ("message-1", item_id)
    assert "status = 'done'" in calls[1][0]
    assert "finished_at = now()" in calls[1][0]
    assert calls[1][1] == (42, 3.2, item_id, claim_token)
    assert "status = 'retrying'" in calls[2][0]
    assert calls[2][1] == (1.5, item_id, claim_token)
    assert "status = 'error'" in calls[3][0]
    assert "finished_at = now()" in calls[3][0]
    assert calls[3][1] == ("invalid_request", "no filing found", 1.5, item_id, claim_token)


class _StatefulResult:
    def __init__(self, row=None, rowcount: int = 0):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class _StatefulConn:
    """Minimal in-memory model of the fenced ingest-job updates."""

    def __init__(self, rows):
        self.rows = rows
        self.inserted_rows = []

    def _tuple_for(self, row):
        return (
            row["id"],
            row["batch_id"],
            row["ticker"],
            row["form_type"],
            row["year"],
            row["period"],
            row["status"],
            row["attempts"],
            row["claim_token"],
            row["qstash_message_id"],
            row["chunks"],
            row["elapsed_s"],
            row["error_code"],
            row["error_message"],
        )

    def executemany(self, sql, params):
        assert "ON CONFLICT (id) DO NOTHING" in sql
        for row in params:
            if row[0] not in self.rows:
                self.rows[row[0]] = {
                    "id": row[0],
                    "batch_id": row[1],
                    "ticker": row[2],
                    "form_type": row[3],
                    "year": row[4],
                    "period": row[5],
                    "status": "queued",
                    "attempts": 0,
                    "claim_token": None,
                    "qstash_message_id": None,
                    "chunks": None,
                    "elapsed_s": None,
                    "error_code": None,
                    "error_message": None,
                    "updated_age_s": 0,
                }
            self.inserted_rows.append(row)

    def execute(self, sql, params):
        if "SELECT status, claim_token::text, chunks, elapsed_s, error_code, error_message" in sql:
            row = self.rows.get(params[0])
            if row is None:
                return _StatefulResult()
            return _StatefulResult(
                (
                    row["status"],
                    row["claim_token"],
                    row["chunks"],
                    row["elapsed_s"],
                    row["error_code"],
                    row["error_message"],
                )
            )

        if "attempts = CASE" in sql:
            assert "interval '330 seconds'" in sql
            assert "claim_token = %s::uuid" in sql
            compare_token, claim_token, item_id, replay_token = params
            assert compare_token == claim_token == replay_token
            row = self.rows.get(item_id)
            if row is None:
                return _StatefulResult()
            eligible = (
                row["status"] in {"queued", "retrying"}
                or (row["status"] == "running" and row["updated_age_s"] > 330)
                or (row["status"] == "running" and row["claim_token"] == claim_token)
            )
            if not eligible:
                return _StatefulResult()
            if row["claim_token"] != claim_token:
                row["attempts"] += 1
            row["status"] = "running"
            row["claim_token"] = claim_token
            row["updated_age_s"] = 0
            row["error_code"] = None
            row["error_message"] = None
            return _StatefulResult(self._tuple_for(row), 1)

        if "SET status = 'done'" in sql:
            chunks, elapsed_s, item_id, claim_token = params
            row = self.rows[item_id]
            if row["status"] != "running" or row["claim_token"] != claim_token:
                return _StatefulResult()
            row.update(status="done", chunks=chunks, elapsed_s=elapsed_s)
            return _StatefulResult(rowcount=1)

        if "SET status = 'retrying'" in sql:
            elapsed_s, item_id, claim_token = params
            row = self.rows[item_id]
            if row["status"] != "running" or row["claim_token"] != claim_token:
                return _StatefulResult()
            row.update(status="retrying", elapsed_s=elapsed_s)
            return _StatefulResult(rowcount=1)

        if "SET status = 'error'" in sql:
            if len(params) == 5:
                code, message, elapsed_s, item_id, claim_token = params
                row = self.rows[item_id]
                accepted = row["status"] == "running" and row["claim_token"] == claim_token
            else:
                code, message, elapsed_s, item_id = params
                row = self.rows[item_id]
                accepted = row["status"] != "done"
            if not accepted:
                return _StatefulResult()
            row.update(status="error", error_code=code, error_message=message)
            if elapsed_s is not None:
                row["elapsed_s"] = elapsed_s
            return _StatefulResult(rowcount=1)

        raise AssertionError(f"Unexpected SQL: {sql}")


def _job_row(*, status="queued", attempts=0, claim_token=None, updated_age_s=0):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "batch_id": "00000000-0000-0000-0000-000000000002",
        "ticker": "AAPL",
        "form_type": "10-K",
        "year": 2024,
        "period": None,
        "status": status,
        "attempts": attempts,
        "claim_token": claim_token,
        "qstash_message_id": None,
        "chunks": None,
        "elapsed_s": None,
        "error_code": None,
        "error_message": None,
        "updated_age_s": updated_age_s,
    }


def test_claim_replay_returns_the_same_token_without_double_counting(monkeypatch):
    row = _job_row()
    conn = _StatefulConn({row["id"]: row})

    def replaying_write(fn):
        fn(conn)
        return fn(conn)

    monkeypatch.setattr(ingest_jobs.db, "run_write", replaying_write)

    claimed = ingest_jobs.claim(row["id"])

    assert claimed["claim_token"] == row["claim_token"]
    assert row["attempts"] == 1


def test_claim_rejects_fresh_running_and_terminal_rows(monkeypatch):
    current_token = str(uuid.uuid4())
    running = _job_row(status="running", attempts=1, claim_token=current_token)
    done = _job_row(status="done", attempts=1, claim_token=current_token)
    done["id"] = "00000000-0000-0000-0000-000000000003"
    conn = _StatefulConn({running["id"]: running, done["id"]: done})
    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(conn))

    assert ingest_jobs.claim(running["id"]) is None
    assert ingest_jobs.claim(done["id"]) is None
    assert running["attempts"] == done["attempts"] == 1


def test_claim_reclaims_a_stale_running_row_with_a_new_token(monkeypatch):
    old_token = str(uuid.uuid4())
    row = _job_row(status="running", attempts=1, claim_token=old_token, updated_age_s=331)
    conn = _StatefulConn({row["id"]: row})
    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(conn))

    claimed = ingest_jobs.claim(row["id"])

    assert claimed["claim_token"] != old_token
    assert row["attempts"] == 2


def test_stale_worker_transitions_are_rejected_without_terminal_regression(monkeypatch):
    old_token = str(uuid.uuid4())
    current_token = str(uuid.uuid4())
    row = _job_row(status="running", attempts=2, claim_token=current_token)
    conn = _StatefulConn({row["id"]: row})
    monkeypatch.setattr(ingest_jobs.db, "run_write", lambda fn: fn(conn))

    assert not ingest_jobs.mark_done(row["id"], claim_token=old_token, chunks=42, elapsed_s=2.0)
    assert not ingest_jobs.mark_retrying(row["id"], claim_token=old_token, elapsed_s=2.0)
    assert not ingest_jobs.mark_error(
        row["id"], claim_token=old_token, code="stale", message="stale worker"
    )
    assert ingest_jobs.mark_done(row["id"], claim_token=current_token, chunks=42, elapsed_s=2.0)
    assert row["status"] == "done"
    assert not ingest_jobs.mark_retrying(row["id"], claim_token=current_token, elapsed_s=3.0)
    assert not ingest_jobs.mark_error(
        row["id"], claim_token=None, code="delivery", message="late failure"
    )
    assert row["status"] == "done"


def test_create_batch_replay_is_harmless_with_stable_generated_ids(monkeypatch):
    generated_ids = iter(
        [
            uuid.UUID("00000000-0000-0000-0000-000000000010"),
            uuid.UUID("00000000-0000-0000-0000-000000000011"),
            uuid.UUID("00000000-0000-0000-0000-000000000012"),
        ]
    )
    monkeypatch.setattr(ingest_jobs.uuid, "uuid4", lambda: next(generated_ids))
    conn = _StatefulConn({})

    def replaying_write(fn):
        fn(conn)
        return fn(conn)

    monkeypatch.setattr(ingest_jobs.db, "run_write", replaying_write)

    batch_id, item_ids = ingest_jobs.create_batch(
        ["AAPL", "MSFT"], form_type="10-K", year=2024, period=None
    )

    assert batch_id == "00000000-0000-0000-0000-000000000010"
    assert set(conn.rows) == set(item_ids)
    assert len(conn.rows) == 2
    assert len(conn.inserted_rows) == 4


def test_malformed_uuid_reads_and_claim_do_not_touch_the_database(monkeypatch):
    monkeypatch.setattr(
        ingest_jobs.db, "query", lambda *args: (_ for _ in ()).throw(AssertionError("query called"))
    )
    monkeypatch.setattr(
        ingest_jobs.db,
        "run_write",
        lambda *args: (_ for _ in ()).throw(AssertionError("write called")),
    )

    assert ingest_jobs.get_batch("not-a-uuid") is None
    assert ingest_jobs.get_item("not-a-uuid") is None
    assert ingest_jobs.claim("not-a-uuid") is None


def test_mark_done_replay_confirms_the_same_persisted_transition(monkeypatch):
    claim_token = str(uuid.uuid4())
    row = _job_row(status="running", claim_token=claim_token)
    conn = _StatefulConn({row["id"]: row})

    def replaying_write(fn):
        assert fn(conn)
        return fn(conn)

    monkeypatch.setattr(ingest_jobs.db, "run_write", replaying_write)

    assert ingest_jobs.mark_done(row["id"], claim_token=claim_token, chunks=42, elapsed_s=2.0)
    assert row["status"] == "done"


def test_mark_retrying_replay_confirms_the_same_persisted_transition(monkeypatch):
    claim_token = str(uuid.uuid4())
    row = _job_row(status="running", claim_token=claim_token)
    conn = _StatefulConn({row["id"]: row})

    def replaying_write(fn):
        assert fn(conn)
        return fn(conn)

    monkeypatch.setattr(ingest_jobs.db, "run_write", replaying_write)

    assert ingest_jobs.mark_retrying(row["id"], claim_token=claim_token, elapsed_s=2.0)
    assert row["status"] == "retrying"


def test_mark_error_replay_confirms_the_same_persisted_transition(monkeypatch):
    claim_token = str(uuid.uuid4())
    row = _job_row(status="running", claim_token=claim_token)
    conn = _StatefulConn({row["id"]: row})

    def replaying_write(fn):
        assert fn(conn)
        return fn(conn)

    monkeypatch.setattr(ingest_jobs.db, "run_write", replaying_write)

    assert ingest_jobs.mark_error(
        row["id"],
        claim_token=claim_token,
        code="transient_failure",
        message="upstream unavailable",
        elapsed_s=2.0,
    )
    assert row["status"] == "error"


def test_record_message_rejects_a_malformed_item_uuid_without_a_database_write(monkeypatch):
    monkeypatch.setattr(
        ingest_jobs.db,
        "run_write",
        lambda *args: (_ for _ in ()).throw(AssertionError("write called")),
    )

    assert not ingest_jobs.record_message("not-a-uuid", "message-1")
