"""FastAPI public surface (Wave 5A) — the HTTP entry point for the demo.

Endpoints
---------
- GET  /health          — liveness + whether Langfuse tracing is active
- POST /ask             — RAG question, streamed as Server-Sent Events
- POST /agent           — multi-step ReAct agent, returns the final answer + steps
- POST /ingest          — persist and enqueue an ingest batch (202 + job_id)
- GET  /ingest/{job_id} — poll an ingest job's status/results
- POST /internal/ingest/run     — run one signed QStash delivery
- POST /internal/ingest/failure — record final QStash delivery failure

Each request is wrapped in one Langfuse trace and a token meter (Wave 5B), so the
response carries per-request latency, token usage, estimated USD cost, and a link
to the trace. The heavy work (DB + LLM calls) is blocking, so it runs in a thread
pool to keep the event loop responsive while SSE streams status to the client.

Public exposure (Wave 5A): set API_TOKEN to require `Authorization: Bearer <token>`
on /ask /agent /ingest (/health stays open); set API_ROOT_PATH when served under a
path prefix behind a proxy. Both default off, so local dev and tests are unchanged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import time
from functools import partial

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from src import config, cost, ingest_jobs, obs, qstash_queue
from src.agent import run_agent
from src.db import bootstrap
from src.ingest import ingest as run_ingest
from src.rag import ask as run_ask

logger = logging.getLogger(__name__)

# root_path lets the app sit behind a path-stripping proxy (e.g. a Cloudflare
# Worker routing www.example.com/finrag/* → here): routes stay at "/", while
# /docs and the OpenAPI server URL pick up the prefix. Empty by default (root).
app = FastAPI(
    title="finrag",
    description="RAG + agent over SEC filings",
    version="0.5.0",
    root_path=config.api_root_path(),
)

# SSE heartbeat interval. The blocking pipeline can run > 100 s (Neon cold start
# + LLM); Cloudflare cuts idle connections at ~100 s, so the stream must carry
# comment pings well inside that window while the worker thread runs.
_SSE_PING_SECONDS = 15

# Per-route rate limits (enforced only when RATE_LIMIT_ENABLED is set). Sized to
# the cost of each route: /agent runs up to 20 LLM calls, /ingest fetches EDGAR
# and embeds thousands of chunks. GET /ingest/{job_id} stays unlimited because
# it is a cheap Neon status poll used every few seconds while a job runs.
_RATE_ASK = "10/minute"
_RATE_AGENT = "3/minute"
_RATE_INGEST = "2/hour"
_IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")


def _rate_key(request: Request) -> str:
    """Rate-limit bucket key: bearer token when present, else the client IP.

    A shared token maps to ONE global bucket — the point is capping total spend
    on the free LLM/embedding quotas, not per-user fairness. The token is hashed
    so it never appears in limiter storage or error messages. Unauthenticated
    requests bucket by IP; behind the Cloudflare tunnel the socket peer is
    localhost, so trust the proxy-provided client IP headers first.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return "tok:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "anonymous")
    )


limiter = Limiter(key_func=_rate_key, enabled=config.rate_limit_enabled())
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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
    top_k: int = Field(default=5, ge=1, le=config.MAX_TOP_K)


class AgentRequest(BaseModel):
    question: str = Field(min_length=1)
    max_steps: int = Field(default=8, ge=1, le=20)


class IngestRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=5)
    form_type: str = "10-K"
    year: int | None = Field(default=None, ge=1994, le=2030)
    period: str | None = None

    @model_validator(mode="after")
    def _require_year_or_period(self) -> IngestRequest:
        if self.year is None and self.period is None:
            raise ValueError("provide year or period")
        return self


class IngestWorkerRequest(BaseModel):
    """Identify one persisted ingest item delivered by QStash."""

    item_id: str = Field(min_length=1, max_length=64)


class QStashFailureRequest(BaseModel):
    """Represent the fields needed from a QStash failure callback."""

    source_body: str = Field(alias="sourceBody")
    retried: int
    max_retries: int = Field(alias="maxRetries")


def _period_of(req: AskRequest) -> str | None:
    """Explicit --period wins; otherwise derive a year filter."""
    if req.period:
        return req.period
    return str(req.year) if req.year else None


def _validated_idempotency_key(value: str | None) -> str:
    """Return a safe stable submission key or reject the request."""
    if value is None:
        raise HTTPException(status_code=400, detail="missing Idempotency-Key header")
    if not _IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail="invalid Idempotency-Key header")
    return value


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
    # Priced from the per-model usage buckets (the model that actually served
    # each call), not the configured default model.
    cost_usd, cost_known = cost.estimate_meter(usage)
    return {
        "text": answer.text,
        "citations": [c.model_dump() for c in answer.citations],
        "usage": usage,
        "cost_usd": round(cost_usd, 6),
        "cost_estimated": cost_known,
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
    cost_usd, cost_known = cost.estimate_meter(usage)
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
        "cost_usd": round(cost_usd, 6),
        "cost_estimated": cost_known,
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "trace_url": obs.trace_url(trace_id),
    }


# Generic client-facing message for unexpected failures. Raw exception strings
# can leak DSNs / internal paths, so they go to the server log only.
_INTERNAL_ERROR = "internal error — see server logs"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tracing": obs.enabled()}


@app.post("/ask", dependencies=[Depends(require_token)])
@limiter.limit(_RATE_ASK)
async def ask(request: Request, req: AskRequest) -> EventSourceResponse:
    """Answer a question, streamed as SSE: status → answer → done (or error)."""

    async def events():
        yield {"event": "status", "data": json.dumps({"stage": "processing"})}
        try:
            result = await run_in_threadpool(_ask_sync, req)
        except ValueError as exc:
            # Domain errors (nothing ingested, rejected citation) are intentional,
            # client-safe messages.
            yield {"event": "error",
                   "data": json.dumps({"code": "invalid_request", "error": str(exc)})}
            return
        except Exception:  # noqa: BLE001 — unexpected details stay in server logs
            logger.exception("/ask failed")
            yield {"event": "error",
                   "data": json.dumps({"code": "internal_error", "error": _INTERNAL_ERROR})}
            return
        yield {"event": "answer", "data": json.dumps(result)}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(events(), ping=_SSE_PING_SECONDS)


@app.post("/agent", dependencies=[Depends(require_token)])
@limiter.limit(_RATE_AGENT)
async def agent(request: Request, req: AgentRequest) -> dict:
    return await run_in_threadpool(_agent_sync, req)


@app.post("/ingest", status_code=202, dependencies=[Depends(require_token)])
@limiter.limit(_RATE_INGEST)
async def ingest(
    request: Request,
    req: IngestRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """Persist and enqueue a retry-safe batch keyed by `Idempotency-Key`."""
    idempotency_key = _validated_idempotency_key(idempotency_key)
    await run_in_threadpool(bootstrap)
    try:
        batch_id, item_ids = await run_in_threadpool(
            partial(
                ingest_jobs.create_batch,
                [ticker.upper() for ticker in req.tickers],
                form_type=req.form_type,
                year=req.year,
                period=req.period,
                idempotency_key=idempotency_key,
            )
        )
    except ingest_jobs.IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_conflict",
                "error": "Idempotency-Key was already used for a different request",
            },
        ) from exc

    publish_failed = False
    for item_id in item_ids:
        try:
            message_id = await run_in_threadpool(
                qstash_queue.publish_ingest_item, item_id
            )
        except Exception:  # noqa: BLE001 — ambiguous delivery stays queued
            publish_failed = True
            logger.exception("failed to publish ingest item %s", item_id)
            continue

        try:
            recorded = await run_in_threadpool(
                ingest_jobs.record_message, item_id, message_id
            )
            if not recorded:
                logger.warning(
                    "failed to record QStash message id for item %s", item_id
                )
        except Exception:  # noqa: BLE001 — the QStash message is already durable
            logger.exception(
                "failed to record QStash message id for item %s", item_id
            )

    if publish_failed:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "queue_publish_failed",
                "error": "unable to queue one or more ingest jobs",
                "job_id": batch_id,
                "retryable": True,
                "retry": "retry with the same Idempotency-Key",
            },
        )
    return {
        "job_id": batch_id,
        "status": "queued",
        "poll": f"/ingest/{batch_id}",
    }


@app.get("/ingest/{job_id}", dependencies=[Depends(require_token)])
async def ingest_status(job_id: str) -> dict:
    """Return the persisted aggregate state for an ingest batch."""
    job = await run_in_threadpool(ingest_jobs.get_batch, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown ingest job")
    return job


async def _verified_qstash_body(request: Request) -> bytes:
    """Return the raw request body after verifying its QStash signature."""
    raw_body = await request.body()
    signature = request.headers.get("Upstash-Signature", "")
    if not signature:
        raise HTTPException(status_code=401, detail="missing QStash signature")
    try:
        qstash_queue.verify(
            body=raw_body,
            signature=signature,
            url=str(request.url),
        )
    except Exception as exc:  # noqa: BLE001 — verifier errors share one safe response
        logger.exception("QStash signature verification failed")
        raise HTTPException(
            status_code=401, detail="invalid QStash signature"
        ) from exc
    return raw_body


async def _response_after_rejected_transition(item_id: str) -> dict:
    """Return an idempotent response for terminal state, otherwise request retry."""
    existing = await run_in_threadpool(ingest_jobs.get_item, item_id)
    if existing and existing["status"] in ingest_jobs.TERMINAL_STATUSES:
        return {"status": "already_processed"}
    raise HTTPException(status_code=503, detail="ingest item is active")


@app.post("/internal/ingest/run")
async def run_ingest_item(request: Request) -> dict:
    """Run one signed QStash ingest delivery with token-fenced transitions."""
    raw_body = await _verified_qstash_body(request)
    try:
        payload = IngestWorkerRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid ingest item") from exc

    item = await run_in_threadpool(ingest_jobs.claim, payload.item_id)
    if item is None:
        return await _response_after_rejected_transition(payload.item_id)

    claim_token = item["claim_token"]
    started = time.monotonic()
    try:
        chunks = await run_in_threadpool(
            partial(
                run_ingest,
                item["ticker"],
                form_type=item["form_type"],
                period=item["period"],
                fiscal_year=item["year"],
            )
        )
    except ValueError as exc:
        elapsed = round(time.monotonic() - started, 1)
        accepted = await run_in_threadpool(
            partial(
                ingest_jobs.mark_error,
                payload.item_id,
                code="invalid_request",
                message=str(exc),
                elapsed_s=elapsed,
                claim_token=claim_token,
            )
        )
        if not accepted:
            return await _response_after_rejected_transition(payload.item_id)
        return {"status": "error"}
    except Exception as exc:  # noqa: BLE001 — unexpected details stay server-side
        elapsed = round(time.monotonic() - started, 1)
        logger.exception("ingest item %s failed transiently", payload.item_id)
        accepted = await run_in_threadpool(
            partial(
                ingest_jobs.mark_retrying,
                payload.item_id,
                claim_token=claim_token,
                elapsed_s=elapsed,
            )
        )
        if not accepted:
            return await _response_after_rejected_transition(payload.item_id)
        raise HTTPException(status_code=503, detail=_INTERNAL_ERROR) from exc

    elapsed = round(time.monotonic() - started, 1)
    accepted = await run_in_threadpool(
        partial(
            ingest_jobs.mark_done,
            payload.item_id,
            claim_token=claim_token,
            chunks=chunks,
            elapsed_s=elapsed,
        )
    )
    if not accepted:
        return await _response_after_rejected_transition(payload.item_id)
    return {"status": "done", "chunks": chunks}


@app.post("/internal/ingest/failure")
async def ingest_delivery_failure(request: Request) -> dict:
    """Record final QStash delivery failure without overwriting completed work."""
    raw_body = await _verified_qstash_body(request)
    try:
        callback = QStashFailureRequest.model_validate_json(raw_body)
        source_body = base64.b64decode(callback.source_body, validate=True)
        payload = IngestWorkerRequest.model_validate_json(source_body)
    except (binascii.Error, ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="invalid QStash failure callback"
        ) from exc

    accepted = await run_in_threadpool(
        partial(
            ingest_jobs.mark_error,
            payload.item_id,
            code="delivery_failed",
            message="ingest delivery failed after retries",
        )
    )
    if not accepted:
        return await _response_after_rejected_transition(payload.item_id)
    return {"status": "error"}
