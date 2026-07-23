# Wave 5B — Observability, cost, caching

## What shipped

- `src/obs.py` — fail-open Langfuse wrapper. One trace per request; inner spans
  auto-nest via OpenTelemetry context, so no trace id is threaded through the call
  chain. Wired into the three hot paths:
  - `llm.chat()` → a `generation` span carrying model, token `usage_details`, and
    `cost_details` (USD).
  - `retrieve.retrieve()` → a `retriever` span carrying mode/rewrite/rerank and the
    returned chunk ids.
  - `tools.run_tool()` → a `tool` span per agent tool call.
  Degrades to a no-op when `LANGFUSE_*` keys are unset, the SDK is missing, or
  Langfuse Cloud is unreachable — tracing must never break or slow a request.
- `src/obs.py` request meter — a ContextVar counter that aggregates token usage
  across every `chat()` call in one request; the API reads it for `$/query`.
- `src/cost.py` — token → USD table. NVIDIA NIM open-weight = $0; closed backups
  carry public list prices so a provider switch yields a real cost line.
- `src/clients/anthropic.py` — system prompt sent as an ephemeral-cache block
  (`cache_control: {type: ephemeral}`); `llm.py` already reads
  `cache_read_input_tokens` / `cache_creation_input_tokens` back.

## Hypothesis (first commit)

"Caching the system prompt + tool schemas drops p50 latency ≥ 30% and $/query
≥ 40%; if it's under half that, cache hit-rate isn't materializing and the cache
key is churning." **Status: not live-measurable this run** — Anthropic credits are
exhausted (the only provider with an ephemeral-cache API here), so the cache path
is implemented and unit-covered but the before/after delta can't be measured. The
NVIDIA NIM primary has no documented prompt-cache API, so its cost is already $0
and latency is generation-bound, not input-bound.

## Measured (live, NVIDIA NIM `llama-3.3-70b`, `/ask` over HTTP)

| metric | value |
|---|---|
| p50 latency | ~12.6s (5-run sample: 8.3 / 10.8 / 12.7 / 16.2 / 45.0s) |
| tokens / query | ~1.7k input + ~50 output |
| **$/query** | **$0.000000** (open-weight free tier) |
| LLM calls / RAG query | 1 (generation); +1 per query-rewrite variant |
| LLM calls / agent query | = steps (one generation per ReAct turn) |

`cost.estimate` against the closed-backup table (unit-tested): a 1M-in/1M-out
request on `gemini-2.5-flash` = **$2.80**, the reference point for what the free
NVIDIA path saves per heavy query.

## Tracing status — verified live

With `LANGFUSE_*` keys set, `GET /health` reports `tracing:true` and a `/ask` call
returns a real trace link, e.g.:

```
text: "Apple operating income in fiscal 2024 was $123,216"
trace_url: https://…cloud.langfuse.com/project/…/traces/2052facf…ff2e15
```

The trace contains the `api.ask` → `retrieve` (retriever) + `llm.nvidia`
(generation, with token usage + USD cost) span tree; agent requests add a
`tool.*` span per ReAct tool call. Fail-open is also verified: with the keys
blank, `tracing:false`, every `obs.span()` is a no-op, `trace_url` is null, and
answers are unchanged.

## Scoped out, with reasons (not silently dropped)

- **Gemini explicit cache around filing context** — Gemini 2.5 `CachedContent` has a
  hard minimum of 32,768 tokens; a RAG context here is ~1.7k tokens, ~20× below the
  floor, so a cache create call would just error. It's the wrong tool for chunk-sized
  context; the right place for Gemini explicit cache is a whole-filing agent context,
  which this pipeline doesn't send. Left unimplemented rather than shipping a path
  that can't run.
- **Token-level streaming of the answer** — `/ask` streams SSE *events*
  (`status → answer → done`), not tokens. The answer is a structured, citation-
  validated JSON object: partial JSON can't be shown to the user (a half-streamed
  citation may point at a hallucinated chunk and get rejected at the end). Streaming
  status keeps the UI responsive; streaming raw JSON tokens would leak unvalidated
  text. A token-streamed *plain-prose* mode is a clean Wave 7 add if needed.

## Theory ↔ Practice (LLM Engineer §6 Inference Optimization + §7 observability)

The chapter's claim is that the biggest cheap win is caching the stable prefix
(system prompt + tool schemas). Here the bite is provider-shaped: the open-weight
primary is already free and has no cache API, so the optimization that matters for
*this* stack is latency (streaming + a warm reranker), not $/token. The cost
machinery still earns its place as a guardrail — it makes a future switch to a
paid closed model show up as a number in the trace and the report instead of a
surprise on the bill.
