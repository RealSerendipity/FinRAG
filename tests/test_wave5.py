"""Wave 5 tests — cost estimation, the request meter, and the FastAPI surface.

The API tests stub run_ask / run_agent so they exercise the HTTP + SSE plumbing
without hitting the DB or an LLM (network-free, no key needed).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src import api, cost, obs
from src.financial.schemas import Answer, Citation


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


def test_ingest_returns_202_with_pollable_job(monkeypatch):
    # Ingest runs minutes (EDGAR fetch + embedding); a synchronous response dies
    # at proxy timeouts. The route must accept, return a job id, and expose status.
    monkeypatch.setattr(api, "run_ingest", lambda ticker, **k: 42)
    resp = client.post("/ingest", json={"tickers": ["AAPL"], "year": 2024})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    status = client.get(f"/ingest/{job_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "done"
    assert body["results"][0] == {
        "ticker": "AAPL",
        "chunks": 42,
        "elapsed_s": body["results"][0]["elapsed_s"],
    }


def test_ingest_job_records_per_ticker_errors(monkeypatch):
    def _boom(ticker, **k):
        raise ValueError("no filing found")

    monkeypatch.setattr(api, "run_ingest", _boom)
    resp = client.post("/ingest", json={"tickers": ["ZZZZ"], "year": 2024})
    job_id = resp.json()["job_id"]
    body = client.get(f"/ingest/{job_id}").json()
    assert body["status"] == "done"
    # Domain ValueErrors carry intentional, safe messages (no exception type noise).
    assert "no filing found" in body["results"][0]["error"]


def test_ingest_unknown_job_is_404():
    assert client.get("/ingest/nonexistent").status_code == 404


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
    monkeypatch.setattr(api, "run_ingest", lambda ticker, **k: 1)
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
