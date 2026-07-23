"""Wave 5 tests — cost estimation, the request meter, and the FastAPI surface.

The API tests stub run_ask / run_agent so they exercise the HTTP + SSE plumbing
without hitting the DB or an LLM (network-free, no key needed).
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from src import api, cost, obs
from src.financial.schemas import Answer, Citation


@pytest.fixture(autouse=True)
def _disable_api_token(monkeypatch):
    """Keep API tests isolated from a developer's local `.env` credentials."""
    monkeypatch.delenv("API_TOKEN", raising=False)


# --------------------------------------------------------------------------- #
# cost
# --------------------------------------------------------------------------- #
def test_cost_free_tier_is_zero():
    usage = {"input_tokens": 1000, "output_tokens": 500}
    assert cost.estimate("meta/llama-3.3-70b-instruct", usage) == 0.0


def test_cost_priced_model():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    # gemini-2.5-flash = (0.30 input, 2.50 output) per 1M
    assert cost.estimate("gemini-2.5-flash", usage) == 0.30 + 2.50
    details = cost.cost_details("gemini-2.5-flash", usage)
    assert details["total"] == details["input"] + details["output"] == 2.80


def test_cost_unknown_model_defaults_to_zero():
    assert cost.estimate("some/unlisted-model", {"input_tokens": 9, "output_tokens": 9}) == 0.0


# --------------------------------------------------------------------------- #
# obs request meter (works regardless of whether Langfuse is configured)
# --------------------------------------------------------------------------- #
def test_request_meter_accumulates():
    with obs.request_meter() as meter:
        obs.record_usage({"input_tokens": 10, "output_tokens": 3})
        obs.record_usage({"input_tokens": 5, "output_tokens": 2})
    assert meter == {"input_tokens": 15, "output_tokens": 5, "calls": 2}


def test_record_usage_outside_meter_is_noop():
    # No active meter → must not raise.
    obs.record_usage({"input_tokens": 1, "output_tokens": 1})


def test_span_noop_when_disabled():
    # With no Langfuse keys, span() yields a handle whose update() is harmless.
    with obs.span("x", as_type="generation") as sp:
        sp.update(output="ok", usage_details={"input_tokens": 1})


# --------------------------------------------------------------------------- #
# FastAPI surface
# --------------------------------------------------------------------------- #
client = TestClient(api.app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "tracing" in body


def test_ask_sse_stream(monkeypatch):
    monkeypatch.setattr(
        api, "run_ask",
        lambda q, **k: Answer(text="Revenue was $X", citations=[Citation(chunk_id=7, quote="q")]),
    )
    resp = client.post("/ask", json={"question": "revenue?", "ticker": "AAPL", "top_k": 3})
    assert resp.status_code == 200
    assert "event: status" in resp.text
    assert "event: answer" in resp.text
    assert "Revenue was $X" in resp.text
    assert '"chunk_id": 7' in resp.text


def test_ask_sse_error_event(monkeypatch):
    def _boom(q, **k):
        raise ValueError("No chunks found")

    monkeypatch.setattr(api, "run_ask", _boom)
    resp = client.post("/ask", json={"question": "revenue?"})
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "No chunks found" in resp.text


def test_ask_rejects_empty_question():
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_agent_endpoint(monkeypatch):
    class _Step:
        thought, action, action_input, observation = "t", "calculator", {"e": "1+1"}, "2"

    class _Result:
        answer = "two"
        steps = [_Step()]
        tools_used = ["calculator"]
        stopped = "final_answer"

    monkeypatch.setattr(api, "run_agent", lambda q, **k: _Result())
    resp = client.post("/agent", json={"question": "1+1?", "max_steps": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "two"
    assert body["tools_used"] == ["calculator"]
    assert body["steps"][0]["action"] == "calculator"


def test_ingest_requires_year_or_period():
    # Missing year/period is a validation error, not a 200 with an error body.
    resp = client.post("/ingest", json={"tickers": ["AAPL"]})
    assert resp.status_code == 422


def test_ingest_returns_persisted_job_and_publishes_each_item(monkeypatch):
    monkeypatch.setattr(api, "bootstrap", lambda: None)
    created = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "create_batch",
        lambda *args, **kwargs: (
            created.append((args, kwargs)) or ("batch-1", ["item-1", "item-2"])
        ),
    )
    published = []
    monkeypatch.setattr(
        api.qstash_queue,
        "publish_ingest_item",
        lambda item_id: published.append(item_id) or f"msg-{item_id}",
    )
    recorded = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "record_message",
        lambda item_id, message_id: recorded.append((item_id, message_id)) or True,
    )

    resp = client.post(
        "/ingest",
        json={"tickers": ["aapl", "msft"], "year": 2024},
    )

    assert resp.status_code == 202
    assert resp.json() == {
        "job_id": "batch-1",
        "status": "queued",
        "poll": "/ingest/batch-1",
    }
    assert created[0][0] == (["AAPL", "MSFT"],)
    assert published == ["item-1", "item-2"]
    assert recorded == [
        ("item-1", "msg-item-1"),
        ("item-2", "msg-item-2"),
    ]


def test_ingest_publish_failure_marks_item_and_continues(monkeypatch):
    monkeypatch.setattr(api, "bootstrap", lambda: None)
    monkeypatch.setattr(
        api.ingest_jobs,
        "create_batch",
        lambda *a, **k: ("batch-1", ["item-1", "item-2"]),
    )
    published = []

    def _publish(item_id):
        published.append(item_id)
        if item_id == "item-1":
            raise RuntimeError("queue unavailable")
        return "msg-2"

    monkeypatch.setattr(api.qstash_queue, "publish_ingest_item", _publish)
    marked = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "mark_error",
        lambda item_id, **kwargs: marked.append((item_id, kwargs)) or True,
    )
    monkeypatch.setattr(api.ingest_jobs, "record_message", lambda *a: True)

    resp = client.post(
        "/ingest",
        json={"tickers": ["AAPL", "MSFT"], "year": 2024},
    )

    assert resp.status_code == 503
    assert resp.json()["detail"]["job_id"] == "batch-1"
    assert published == ["item-1", "item-2"]
    assert marked == [
        (
            "item-1",
            {
                "code": "queue_publish_failed",
                "message": "unable to queue ingest job",
            },
        )
    ]


def test_ingest_record_message_false_or_exception_does_not_fail_submit(
    monkeypatch, caplog
):
    monkeypatch.setattr(api, "bootstrap", lambda: None)
    monkeypatch.setattr(
        api.ingest_jobs,
        "create_batch",
        lambda *a, **k: ("batch-1", ["item-1", "item-2"]),
    )
    monkeypatch.setattr(
        api.qstash_queue,
        "publish_ingest_item",
        lambda item_id: f"msg-{item_id}",
    )
    calls = []

    def _record(item_id, message_id):
        calls.append((item_id, message_id))
        if item_id == "item-1":
            return False
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(api.ingest_jobs, "record_message", _record)

    resp = client.post(
        "/ingest",
        json={"tickers": ["AAPL", "MSFT"], "year": 2024},
    )

    assert resp.status_code == 202
    assert calls == [
        ("item-1", "msg-item-1"),
        ("item-2", "msg-item-2"),
    ]
    assert caplog.text.count("failed to record QStash message id") == 2


def test_ingest_status_reads_persisted_batch(monkeypatch):
    monkeypatch.setattr(
        api.ingest_jobs,
        "get_batch",
        lambda job_id: {
            "job_id": job_id,
            "status": "done",
            "items": [
                {"id": "item-1", "ticker": "AAPL", "status": "done", "attempts": 1}
            ],
            "results": [{"ticker": "AAPL", "chunks": 42, "elapsed_s": 3.2}],
        },
    )

    resp = client.get("/ingest/batch-1")

    assert resp.status_code == 200
    assert resp.json()["results"][0]["chunks"] == 42


def test_ingest_status_unknown_job_is_404(monkeypatch):
    monkeypatch.setattr(api.ingest_jobs, "get_batch", lambda job_id: None)
    assert client.get("/ingest/missing").status_code == 404


def _signed_headers():
    return {"Upstash-Signature": "signed"}


def _accept_signature(monkeypatch):
    monkeypatch.setattr(api.qstash_queue, "verify", lambda **kwargs: None)


def test_ingest_worker_rejects_missing_signature():
    resp = client.post("/internal/ingest/run", json={"item_id": "item-1"})
    assert resp.status_code == 401


def test_ingest_worker_rejects_invalid_signature(monkeypatch):
    def _reject(**kwargs):
        raise ValueError("bad signature detail")

    monkeypatch.setattr(api.qstash_queue, "verify", _reject)
    resp = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid QStash signature"}


def test_ingest_worker_verifies_raw_body_and_exact_url(monkeypatch):
    verified = []
    monkeypatch.setattr(
        api.qstash_queue,
        "verify",
        lambda **kwargs: verified.append(kwargs),
    )
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: None)
    monkeypatch.setattr(
        api.ingest_jobs,
        "get_item",
        lambda item_id: {"id": item_id, "status": "done"},
    )
    raw_body = b'{"item_id":"item-1"}'

    resp = client.post(
        "/internal/ingest/run",
        content=raw_body,
        headers={**_signed_headers(), "Content-Type": "application/json"},
    )

    assert resp.status_code == 200
    assert verified == [
        {
            "body": raw_body,
            "signature": "signed",
            "url": "http://testserver/internal/ingest/run",
        }
    ]


@pytest.mark.parametrize("status", ["done", "error"])
def test_ingest_worker_is_idempotent_when_item_is_terminal(monkeypatch, status):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: None)
    monkeypatch.setattr(
        api.ingest_jobs,
        "get_item",
        lambda item_id: {"id": item_id, "status": status},
    )

    resp = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "already_processed"}


def test_ingest_worker_retries_when_item_is_active_or_missing(monkeypatch):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: None)
    monkeypatch.setattr(
        api.ingest_jobs,
        "get_item",
        lambda item_id: {"id": item_id, "status": "running"},
    )
    active = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )
    monkeypatch.setattr(api.ingest_jobs, "get_item", lambda item_id: None)
    missing = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )

    assert active.status_code == 503
    assert missing.status_code == 503


def _claimed_item():
    return {
        "id": "item-1",
        "ticker": "AAPL",
        "form_type": "10-K",
        "year": 2024,
        "period": None,
        "claim_token": "claim-1",
    }


def test_ingest_worker_marks_domain_error_with_claim_token(monkeypatch):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: _claimed_item())
    monkeypatch.setattr(
        api,
        "run_ingest",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("no filing")),
    )
    errors = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "mark_error",
        lambda item_id, **kwargs: errors.append((item_id, kwargs)) or True,
    )

    resp = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "error"}
    assert errors[0][1]["code"] == "invalid_request"
    assert errors[0][1]["claim_token"] == "claim-1"


def test_ingest_worker_marks_transient_failure_retrying_with_claim_token(monkeypatch):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: _claimed_item())
    monkeypatch.setattr(
        api,
        "run_ingest",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("temporary")),
    )
    retries = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "mark_retrying",
        lambda item_id, **kwargs: retries.append((item_id, kwargs)) or True,
    )

    resp = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )

    assert resp.status_code == 503
    assert retries[0][1]["claim_token"] == "claim-1"


def test_ingest_worker_marks_success_done_with_claim_token(monkeypatch):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: _claimed_item())
    monkeypatch.setattr(api, "run_ingest", lambda *a, **k: 42)
    completed = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "mark_done",
        lambda item_id, **kwargs: completed.append((item_id, kwargs)) or True,
    )

    resp = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "done", "chunks": 42}
    assert completed[0][1]["claim_token"] == "claim-1"


def test_ingest_worker_does_not_report_rejected_transition_as_success(monkeypatch):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "claim", lambda item_id: _claimed_item())
    monkeypatch.setattr(api, "run_ingest", lambda *a, **k: 42)
    monkeypatch.setattr(api.ingest_jobs, "mark_done", lambda *a, **k: False)
    monkeypatch.setattr(
        api.ingest_jobs,
        "get_item",
        lambda item_id: {"id": item_id, "status": "running"},
    )

    resp = client.post(
        "/internal/ingest/run",
        json={"item_id": "item-1"},
        headers=_signed_headers(),
    )

    assert resp.status_code == 503


def test_ingest_failure_callback_marks_item_error_without_claim_token(monkeypatch):
    _accept_signature(monkeypatch)
    errors = []
    monkeypatch.setattr(
        api.ingest_jobs,
        "mark_error",
        lambda item_id, **kwargs: errors.append((item_id, kwargs)) or True,
    )
    source = base64.b64encode(json.dumps({"item_id": "item-1"}).encode()).decode()

    resp = client.post(
        "/internal/ingest/failure",
        json={"sourceBody": source, "retried": 3, "maxRetries": 3},
        headers=_signed_headers(),
    )

    assert resp.status_code == 200
    assert errors[0][0] == "item-1"
    assert errors[0][1]["code"] == "delivery_failed"
    assert errors[0][1].get("claim_token") is None


def test_ingest_failure_callback_rejects_malformed_source_body(monkeypatch):
    _accept_signature(monkeypatch)
    resp = client.post(
        "/internal/ingest/failure",
        json={"sourceBody": "not-base64!", "retried": 3, "maxRetries": 3},
        headers=_signed_headers(),
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "invalid QStash failure callback"}


def test_ingest_failure_callback_does_not_report_done_item_as_error(monkeypatch):
    _accept_signature(monkeypatch)
    monkeypatch.setattr(api.ingest_jobs, "mark_error", lambda *a, **k: False)
    monkeypatch.setattr(
        api.ingest_jobs,
        "get_item",
        lambda item_id: {"id": item_id, "status": "done"},
    )
    source = base64.b64encode(json.dumps({"item_id": "item-1"}).encode()).decode()

    resp = client.post(
        "/internal/ingest/failure",
        json={"sourceBody": source, "retried": 3, "maxRetries": 3},
        headers=_signed_headers(),
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "already_processed"}


def test_ask_sse_ping_is_configured():
    # Behind Cloudflare (100 s idle timeout) the stream must carry heartbeats
    # while the blocking pipeline runs; pin the explicit ping interval.
    import asyncio

    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/ask", "headers": [],
             "query_string": b"", "client": ("127.0.0.1", 1)}
    resp = asyncio.run(api.ask(Request(scope), api.AskRequest(question="q")))
    assert resp.ping_interval == api._SSE_PING_SECONDS
    assert api._SSE_PING_SECONDS < 100


# --------------------------------------------------------------------------- #
# Wave 5A public-exposure controls: bearer-token gate + root_path
# --------------------------------------------------------------------------- #
def test_token_gate(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cret")
    # /health stays open for proxy / uptime checks.
    assert client.get("/health").status_code == 200
    # Missing or wrong token is rejected on the protected routes.
    assert client.post("/ingest", json={"tickers": ["AAPL"], "year": 2024}).status_code == 401
    assert client.get("/ingest/somejob").status_code == 401
    assert client.post(
        "/agent", json={"question": "hi"}, headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    # Correct token passes through (stub run_ask so no DB / LLM is touched).
    monkeypatch.setattr(
        api, "run_ask",
        lambda q, **k: Answer(text="ok", citations=[Citation(chunk_id=1, quote="q")]),
    )
    resp = client.post(
        "/ask", json={"question": "revenue?"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert resp.status_code == 200
    assert "event: answer" in resp.text


def test_token_gate_disabled_by_default(monkeypatch):
    # With API_TOKEN unset, protected routes need no Authorization header.
    monkeypatch.setattr(api, "bootstrap", lambda: None)
    monkeypatch.setattr(
        api.ingest_jobs,
        "create_batch",
        lambda *a, **k: ("batch-1", ["item-1"]),
    )
    monkeypatch.setattr(api.qstash_queue, "publish_ingest_item", lambda item_id: "msg-1")
    monkeypatch.setattr(api.ingest_jobs, "record_message", lambda *a: True)
    resp = client.post("/ingest", json={"tickers": ["AAPL"], "year": 2024})
    assert resp.status_code == 202


def test_api_root_path_normalization(monkeypatch):
    from src import config

    monkeypatch.setenv("API_ROOT_PATH", "finrag/")
    assert config.api_root_path() == "/finrag"
    monkeypatch.setenv("API_ROOT_PATH", "/finrag")
    assert config.api_root_path() == "/finrag"
    monkeypatch.delenv("API_ROOT_PATH", raising=False)
    assert config.api_root_path() == ""
