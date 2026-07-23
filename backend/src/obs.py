"""Observability: a thin, fail-open Langfuse wrapper (Wave 5B).

The LLM / retrieval / tool paths open a `span()` so each public request becomes
one Langfuse trace with nested generation + retriever + tool spans. Inner spans
auto-nest under whatever span the caller opened via OpenTelemetry context, so no
trace id has to be threaded through the call chain.

Tracing must never break or slow a request: when LANGFUSE_* keys are unset, the
SDK is missing, or Langfuse Cloud is unreachable, every entry point degrades to a
no-op (the SDK exports spans on a background thread, so an unreachable host fails
silently rather than blocking).
"""

from __future__ import annotations

import contextlib
import contextvars
import os
from typing import Any

_client: Any = None
_enabled: bool | None = None  # tri-state: None = not yet probed

# Per-request token accounting. A request opens `request_meter()`; every chat()
# call inside it reports usage via `record_usage()`. A ContextVar keeps concurrent
# requests isolated (the bound dict is shared with a thread when work runs under
# starlette's run_in_threadpool, so mutations stay visible to the opener).
_usage_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "finrag_request_usage", default=None
)


class _NoopSpan:
    """Stand-in span when tracing is disabled; swallows every update call."""

    def update(self, **_: Any) -> None:
        pass

    def update_trace(self, **_: Any) -> None:
        pass


_NOOP = _NoopSpan()


def _get_client() -> Any:
    global _client, _enabled
    if _enabled is not None:
        return _client
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    sec = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not (pub and sec):
        _enabled = False
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse()  # reads LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST from env
        _enabled = True
    except Exception:
        _client, _enabled = None, False
    return _client


def enabled() -> bool:
    _get_client()
    return bool(_enabled)


@contextlib.contextmanager
def span(name: str, *, as_type: str = "span", **attrs: Any):
    """Open a Langfuse observation as the current span, or a no-op when disabled.

    `as_type` is one of langfuse's observation types (span | generation |
    retriever | tool | chain). Extra kwargs (input, metadata, model, …) pass
    straight through. The yielded handle has `.update(...)` for attaching output
    / usage_details / cost_details after the work completes.
    """
    client = _get_client()
    if client is None:
        yield _NOOP
        return
    try:
        cm = client.start_as_current_observation(name=name, as_type=as_type, **attrs)
    except Exception:
        yield _NOOP
        return
    with cm as observation:
        yield observation


def current_trace_id() -> str | None:
    client = _get_client()
    if client is None:
        return None
    try:
        return client.get_current_trace_id()
    except Exception:
        return None


def trace_url(trace_id: str | None) -> str | None:
    client = _get_client()
    if client is None or not trace_id:
        return None
    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception:
        return None


@contextlib.contextmanager
def request_meter():
    """Accumulate token usage across every chat() call made inside the block.

    Yields the live counter dict; read it after the block for the request total.
    """
    counter = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    token = _usage_var.set(counter)
    try:
        yield counter
    finally:
        _usage_var.reset(token)


def record_usage(usage: dict[str, int], model: str | None = None) -> None:
    """Add one LLM call's usage to the active request meter, if any.

    When `model` is given the tokens are also bucketed per model, so cost can be
    priced by the model that actually served each call (a request may mix
    generator and judge models) instead of a config-level assumption.
    """
    counter = _usage_var.get()
    if counter is None:
        return
    in_tok = usage.get("input_tokens", 0) or 0
    out_tok = usage.get("output_tokens", 0) or 0
    counter["input_tokens"] += in_tok
    counter["output_tokens"] += out_tok
    counter["calls"] += 1
    if model:
        bucket = counter.setdefault("models", {}).setdefault(
            model, {"input_tokens": 0, "output_tokens": 0}
        )
        bucket["input_tokens"] += in_tok
        bucket["output_tokens"] += out_tok


def flush() -> None:
    """Force-export buffered spans (call at the end of a request)."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        pass
