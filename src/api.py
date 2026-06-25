"""FastAPI public surface (Wave 5A) — the HTTP entry point for the demo.

Endpoints
---------
- GET  /health  — liveness + whether Langfuse tracing is active
- POST /ask      — RAG question, streamed as Server-Sent Events
- POST /agent    — multi-step ReAct agent, returns the final answer + steps
- POST /ingest   — fetch & ingest SEC filings into the vector store

Each request is wrapped in one Langfuse trace and a token meter (Wave 5B), so the
response carries per-request latency, token usage, estimated USD cost, and a link
to the trace. The heavy work (DB + LLM calls) is blocking, so it runs in a thread
pool to keep the event loop responsive while SSE streams status to the client.

Public exposure (Wave 5A): set API_TOKEN to require `Authorization: Bearer <token>`
on /ask /agent /ingest (/health stays open); set API_ROOT_PATH when served under a
path prefix behind a proxy. Both default off, so local dev and tests are unchanged.
"""

from __future__ import annotations

import hmac
import json
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from src import config, cost, obs
from src.agent import run_agent
from src.db import bootstrap
from src.ingest import ingest as run_ingest
from src.rag import ask as run_ask

# root_path lets the app sit behind a path-stripping proxy (e.g. a Cloudflare
# Worker routing www.example.com/finrag/* → here): routes stay at "/", while
# /docs and the OpenAPI server URL pick up the prefix. Empty by default (root).
app = FastAPI(
    title="finrag",
    description="RAG + agent over SEC filings",
    version="0.5.0",
    root_path=config.api_root_path(),
)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Gate a route behind `Authorization: Bearer <API_TOKEN>`.

    No-op when API_TOKEN is unset (local dev, tests). Applied to the mutating /
    expensive routes only — /health stays open for proxy/uptime checks. Uses a
    constant-time compare so the check doesn't leak the token via timing.
    """
    expected = config.api_token()
    if not expected:
        return
    prefix = "Bearer "
    supplied = authorization[len(prefix):] if (authorization or "").startswith(prefix) else ""
    if not (supplied and hmac.compare_digest(supplied, expected)):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    ticker: str | None = None
    year: int | None = Field(default=None, ge=1994, le=2030)
    period: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class AgentRequest(BaseModel):
    question: str = Field(min_length=1)
    max_steps: int = Field(default=8, ge=1, le=20)


class IngestRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=5)
    form_type: str = "10-K"
    year: int | None = Field(default=None, ge=1994, le=2030)
    period: str | None = None


def _period_of(req: AskRequest) -> str | None:
    """Explicit --period wins; otherwise derive a year filter."""
    if req.period:
        return req.period
    return str(req.year) if req.year else None


# --------------------------------------------------------------------------- #
# Blocking workers (run in a thread pool)
# --------------------------------------------------------------------------- #
def _ask_sync(req: AskRequest) -> dict:
    """Run one cited RAG answer, metered and traced. Returns a JSON-able dict."""
    t0 = time.monotonic()
    trace_id = None
    with obs.request_meter() as meter, obs.span(
        "api.ask", input=req.question, metadata={"ticker": req.ticker, "top_k": req.top_k}
    ):
        answer = run_ask(
            req.question, ticker=req.ticker, period=_period_of(req), top_k=req.top_k
        )
        trace_id = obs.current_trace_id()
    usage = dict(meter)
    obs.flush()
    return {
        "text": answer.text,
        "citations": [c.model_dump() for c in answer.citations],
        "usage": usage,
        "cost_usd": round(cost.estimate(config.llm_model(), usage), 6),
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "trace_url": obs.trace_url(trace_id),
    }


def _agent_sync(req: AgentRequest) -> dict:
    t0 = time.monotonic()
    trace_id = None
    with obs.request_meter() as meter, obs.span("api.agent", input=req.question):
        result = run_agent(req.question, max_steps=req.max_steps)
        trace_id = obs.current_trace_id()
    usage = dict(meter)
    obs.flush()
    return {
        "answer": result.answer,
        "steps": [
            {"thought": s.thought, "action": s.action,
             "action_input": s.action_input, "observation": s.observation}
            for s in result.steps
        ],
        "tools_used": result.tools_used,
        "stopped": result.stopped,
        "usage": usage,
        "cost_usd": round(cost.estimate(config.llm_model(), usage), 6),
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "trace_url": obs.trace_url(trace_id),
    }


def _ingest_sync(req: IngestRequest) -> dict:
    bootstrap()
    results: list[dict] = []
    for ticker in req.tickers:
        t0 = time.monotonic()
        try:
            chunks = run_ingest(
                ticker, form_type=req.form_type, period=req.period, fiscal_year=req.year
            )
            results.append({"ticker": ticker, "chunks": chunks,
                            "elapsed_s": round(time.monotonic() - t0, 1)})
        except Exception as exc:  # noqa: BLE001 — report per-ticker, don't fail the batch
            results.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}",
                            "elapsed_s": round(time.monotonic() - t0, 1)})
    return {"results": results}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tracing": obs.enabled()}


@app.post("/ask", dependencies=[Depends(require_token)])
async def ask(req: AskRequest) -> EventSourceResponse:
    """Answer a question, streamed as SSE: status → answer → done (or error)."""

    async def events():
        yield {"event": "status", "data": json.dumps({"stage": "processing"})}
        try:
            result = await run_in_threadpool(_ask_sync, req)
        except Exception as exc:  # noqa: BLE001 — surface failures to the client as an event
            yield {"event": "error", "data": json.dumps({"error": f"{type(exc).__name__}: {exc}"})}
            return
        yield {"event": "answer", "data": json.dumps(result)}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(events())


@app.post("/agent", dependencies=[Depends(require_token)])
async def agent(req: AgentRequest) -> dict:
    return await run_in_threadpool(_agent_sync, req)


@app.post("/ingest", dependencies=[Depends(require_token)])
async def ingest(req: IngestRequest) -> dict:
    if req.period is None and req.year is None:
        return {"error": "provide year or period"}
    return await run_in_threadpool(_ingest_sync, req)
