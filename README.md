# FinRAG

[English](README.md) | [简体中文](README.zh-CN.md)

<p align="center">
  <a href="https://www.realserendipity.org/finrag/">
    <img alt="Live Demo" src="docs/live-demo-badge.svg">
  </a>
</p>

<p align="center">
  <a href="https://www.realserendipity.org/finrag/">
    <img alt="finrag — RAG mode answering over Apple's 10-K with citations" src="docs/rag.png" width="820">
  </a>
</p>

> ### 🔗 Try it live → **[www.realserendipity.org/finrag](https://www.realserendipity.org/finrag/)**
> Ask a question over Apple's 10-K and get a **cited, traceable answer** in the browser — no setup.

## Overview

**FinRAG is a production-shaped retrieval-augmented generation (RAG) + agent system
over SEC EDGAR filings** — 10-K, 10-Q, 8-K, 20-F, and DEF 14A — that answers
investment-research questions about public companies with **traceable, cited
answers**. It's a hands-on LLM application engineering project that grows from a
simple cloud-API RAG baseline into an evaluated, observable, agentic product:
retrieval experiments, financial tools, a public demo, and Model Context Protocol
(MCP) integration.

What makes it stand out:

- **Eval-driven, not vibes** — every retrieval / prompt / ranker change is justified
  by a reproducible evaluation harness (recall@k · MRR · nDCG · faithfulness ·
  answer-relevancy via an LLM judge), with metric deltas committed to git.
- **Hybrid retrieval + reranking** — pgvector dense search fused with Postgres
  tsvector BM25 (RRF) and NVIDIA NeMo reranking; recall@10 **0.72 → 0.885** across the
  Wave 3 ablations.
- **Cited, structured answers** — pydantic-validated answers whose citation IDs must
  point to retrieved filing chunks; unknown chunk IDs reject the answer. Each quote is
  also checked against the cited chunk and returned with `verified: false` when it
  does not match, so the UI labels it **Unverified** instead of silently trusting it.
- **Hand-written ReAct agent + 5 tools** — a from-scratch Thought → Action →
  Observation loop (no framework) over filing retrieval, SEC XBRL metric lookup,
  cross-company comparison, web search, and a calculator, with a LangGraph A/B.
- **MCP server (stdio + remote HTTP)** — exposes finrag's tools over the Model Context
  Protocol; run it locally over stdio or as a proxy-friendly network service. The
  HTTP transport enables bearer authentication when `MCP_TOKEN` is set, which is
  mandatory for any public exposure.
- **Security guardrails + prompt-injection red team** — input / context / output
  screens (direct & indirect injection, jailbreak, system-prompt extraction, PII,
  cross-language attacks) measured by a reproducible attack-success-rate harness:
  **ASR 0.29 → 0.07**.
- **Observability & cost** — fail-open Langfuse tracing with per-request token usage
  and a `$/query` estimate on every answer.
- **Separated web stack** — a Next.js frontend proxies browser requests
  server-side to a FastAPI backend (including raw SSE streaming), so the API
  token never reaches the browser. The UI defaults to English and can switch to
  Chinese; both services are structured as independent Vercel projects.

The target user is a developer, analyst, who wants to inspect how the
system ingests filings, retrieves relevant evidence, validates structured answers,
measures quality, and exposes the workflow through CLI, API, UI, agent tools, and MCP.

## Eval-driven results — Wave 2 → Wave 3

Every retrieval change in this project is justified by the eval harness, not by
intuition. Wave 2 froze a baseline; Wave 3 changed only the retrieval pipeline
and re-ran the *same* suite. Result:

**Eval config** — identical for both columns except retrieval:

| Setting | Value |
| --- | --- |
| Chunking | `fixed` |
| Suite | 38 items |
| Generator | `meta/llama-3.3-70b-instruct` |
| Judge | `nvidia/llama-3.3-nemotron-super-49b-v1` |
| Temperature | 0 |
| Retrieval *(the only variable)* | Wave 2 = dense · Wave 3 = hybrid RRF + cross-encoder rerank |

| Metric | Wave 2 (dense baseline) | Wave 3 (hybrid + rerank) | Δ |
| --- | --- | --- | --- |
| recall@5 | 0.66 | **0.87** | +0.21 |
| recall@10 | 0.80 | **0.97** | +0.17 |
| MRR | 0.64 | **0.80** | +0.16 |
| nDCG@10 | 0.65 | **0.84** | +0.19 |
| citation validity (structural) | 0.82 | **0.97** | +0.15 |
| faithfulness † | 0.84 | **0.97** | +0.13 |
| answer relevancy † | 0.94 | **1.00** | +0.06 |
| correctness † | 0.84 | **0.97** | +0.13 |

Retrieval metrics (recall / MRR / nDCG) are LLM-independent, so their gains are
attributable purely to the retrieval pipeline. † Generation metrics depend on the
NVIDIA judge (with Gemini fallback), so read them as directional, not exact.
These metrics plateau here by design: Wave 4+ optimize *different* axes
(agent task success, latency / \$-per-query, attack-success-rate), not single-shot
retrieval quality. Baseline: [`backend/eval/reports/wave_2.md`](backend/eval/reports/wave_2.md);
winning config: [`backend/eval/reports/wave_3_runeval.md`](backend/eval/reports/wave_3_runeval.md);
per-step ablations: [`backend/eval/reports/wave_3{a..f}.md`](backend/eval/reports/) (also in the
[ablation table](#wave-3-retrieval-ablations) below).

## Roadmap

| Wave | Title                                                                                                                  | Status    | Headline metric                                              |
| ---- | ---------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------------------------------------------ |
| 0    | Foundation (closed LLM dispatch, scaffolding)                                                                          | ✅ shipped | —                                                            |
| 1a   | Postgres + pgvector schema + NVIDIA embedding provider(Asymmetric model for RAG)                                       | ✅ shipped | schema migration idempotent; `embed()` returns 1024d vectors |
| 1b   | Dense retrieval + cited answer (pydantic) over local fixture                                                           | ✅ shipped | structured `Answer` with valid citations                     |
| 1c   | EDGAR ingestion + CLI driver                                                                                           | ✅ shipped | `finrag ingest` + `finrag ask` end-to-end                    |
| 1d   | NVIDIA NIM as cloud open-weight provider                                                                               | ✅ shipped | `LLM_PROVIDER=nvidia` round-trip                             |
| 1.5  | Mini-eval over real AAPL FY2024 10-K (n=7, 6 positive + 1 insufficient) + prompt `v1.1` (insufficient-context returned as JSON, not bare text) | ✅ shipped | hit@5 / recall@5 / MRR / nDCG@5 / structural citation validity / LLM-judge faithfulness — numbers in [`backend/eval/reports/wave1_5_mini_eval.md`](backend/eval/reports/wave1_5_mini_eval.md) |
| 2    | Eval harness (38 curated items × 5 categories, NIM judge + Gemini fallback)                                            | ✅ shipped | recall@10 0.80 / MRR 0.64 / nDCG@10 0.65 / citation validity 0.82 / faithfulness 0.84 / correctness 0.84 — details in [`backend/eval/reports/wave_2.md`](backend/eval/reports/wave_2.md) |
| 3    | Retrieval quality (chunking / table-aware / hybrid / rerank / query rewrite)                                           | ✅ shipped | recall@10 0.72 → **0.885** (hybrid + rerank); see [ablation table](#wave-3-retrieval-ablations) |
| 4    | Hand-written ReAct agent + 5 tools, then LangGraph rewrite                                                              | ✅ shipped | task success **0.94** (17/18) · tool-call accuracy 1.00 · avg 3.0 steps — [`backend/eval/reports/wave_4.md`](backend/eval/reports/wave_4.md), A/B in [`wave_4_langgraph_compare.md`](backend/eval/reports/wave_4_langgraph_compare.md) |
| 5A   | Public demo (FastAPI + Streamlit)                                                                                      | ✅ shipped | 4 routes live over HTTP; SSE answers + citation UI; p50 ≈ 12.6s — [`backend/eval/reports/wave_5a.md`](backend/eval/reports/wave_5a.md) |
| 5B   | Observability, cost, caching                                                                                           | ✅ shipped | Langfuse spans (fail-open) · per-request tokens + `$/query` ($0 on NVIDIA free tier) — [`backend/eval/reports/wave_5b.md`](backend/eval/reports/wave_5b.md) |
| 6    | Security & protocols (prompt-injection red team, output guardrails, MCP server)                                        | ✅ shipped | attack-success-rate **0.29 → 0.07** (indirect injection 0.67 → 0.00); finrag exposed as an MCP server — [`backend/eval/reports/wave_6.md`](backend/eval/reports/wave_6.md) |

### Wave 3 retrieval ablations

Each step is an A/B over the 38-item eval set (retrieval metrics are
LLM-independent, so they are measured directly from `retrieve()` output). Full
methodology and per-category tables in `backend/eval/reports/wave_3{a..f}.md`; each
`backend/experiments/wave3_*.py` reproduces its row.

| Step | Change | Result (vs its baseline) | Shipped? |
| ---- | ------ | ------------------------ | -------- |
| 3a | chunking: fixed vs sentence-window vs parent-doc | recall@10 **fixed 0.722** > parent_doc 0.515 > sentence_window 0.247 | fixed (semantic splits shred tables) |
| 3b | table-aware ingestion (Docling) | numeric+table recall@10 0.738→0.671, **MRR +0.042** | no — extraction lossy on SEC HTML; mixed |
| 3c | hybrid pgvector + tsvector RRF | recall@10 0.722→**0.753** (+0.031), MRR +0.038 | ✅ `RETRIEVAL_MODE=hybrid` |
| 3d | cross-encoder rerank (top-50→10) | recall@10 0.753→**0.885**, MRR 0.681→0.801, nDCG→0.798 | ✅ `RERANK_ENABLED=1` (biggest win) |
| 3e | query rewriting (under-specified queries) | HyDE recall@10 0.622→**0.676** (+0.054); multi-query −0.017 | configurable `QUERY_REWRITE=multi_query\|hyde`; default `none` |
| 3f | embedding: NVIDIA vs Gemini | Gemini recall@10 0.722→**0.788** (+0.066), MRR +0.190 — but 3× dim/cost | no — keep index-matched 1024-d NVIDIA |

**Shipped default: fixed chunking + hybrid RRF + rerank** → recall@10 **0.722 → 0.885**, MRR **0.643 → 0.801**, nDCG@10 **0.610 → 0.798** (dense baseline → winning config; reranker `nvidia/rerank-qa-mistral-4b`, the model served on this account in place of the plan's `-v3`).

**Why `QUERY_REWRITE=none` by default (3e):** against the raw baseline, HyDE trades top-rank precision (MRR −0.038 / nDCG −0.035 / recall@5 −0.047) for coverage (recall@10 +0.054 / hit@5 +0.083 / hit@10 +0.055), and multi-query is roughly neutral — neither is a clean win. The shipped path also keeps ticker/period metadata filtering, which already disambiguates the vague queries rewriting targets, and each rewrite adds an LLM call. So it ships off but stays a per-call toggle. Full per-metric breakdown and the under-specified test setup: [`backend/eval/reports/wave_3e.md`](backend/eval/reports/wave_3e.md).

## Wave 4 — ReAct agent + tools

A hand-written ReAct loop ([`backend/src/agent.py`](backend/src/agent.py)) — Thought → Action →
Observation, no agent framework — over five tools:

| Tool | Source | Use |
| ---- | ------ | --- |
| `retrieve_filing` | hybrid + rerank retriever (Wave 3) | narrative / qualitative facts in ingested filings |
| `lookup_metric` | SEC XBRL `companyconcept` API | one audited annual figure (no RAG) |
| `compare_companies` | SEC XBRL | the same metric across companies, side by side (latest **common** fiscal year when `year` is omitted) |
| `calculator` | AST eval (no `eval`) | ratios, % change, sums |
| `web_search` | Tavily (optional) | out-of-corpus facts |

The split is deliberate: numeric questions hit structured XBRL, not chunked prose.
Each non-blocked local `Agent.run()` writes a replayable JSONL trace to
`runs/<id>.jsonl`. A reused `Agent` instance can retain the last N Q/A pairs, while
the public API calls `run_agent()` with a fresh instance for every request, so memory
does not cross API requests. Over an 18-task multi-step suite
([`backend/eval/agent_questions.jsonl`](backend/eval/agent_questions.jsonl)):

| Metric | Result |
| ------ | ------ |
| task success (LLM-judge correctness) | **0.94** (17/18; the one miss is a stale ground-truth figure, not an agent error) |
| tool-call accuracy | **1.00** |
| average steps / task | **3.0** (≤ 6 target) |

The same loop is rewritten on LangGraph ([`backend/src/agent_lg.py`](backend/src/agent_lg.py)) as a
two-node `StateGraph`; both produce identical tool sequences — see the A/B in
[`backend/eval/reports/wave_4_langgraph_compare.md`](backend/eval/reports/wave_4_langgraph_compare.md).
Run it: `uv --directory backend run python -m src.agent "..."` or `uv --directory backend run python eval/run_eval.py --suite agent`.

> **Design choice — text ReAct vs native tool-calling.** This loop is deliberately
> *text-based*: the model emits `Thought / Action / Action Input (JSON) / Final
> Answer` as plain text and the loop **terminates on `Final Answer:`**, not on the
> API's `tool_calls` field. The cost is depending on the model to honor the format
> (handled with single-arg coercion, a same-line lookahead, and client-side
> truncation at `\nObservation:`); the payoff is that any chat model works with
> **zero code change** — only `LLM_PROVIDER` changes — verified live on both NVIDIA
> and Gemini. Native function-calling is more robust in production (the API
> guarantees structure) but provider-specific; native function-calling is not
> implemented in the current codebase.

## Stack (managed model/data services; no local model runtime)

| Layer                       | Primary                                                              | Options                                       |
| --------------------------- | -------------------------------------------------------------------- | --------------------------------------------- |
| LLM — generation            | **NVIDIA NIM** `meta/llama-3.3-70b-instruct` (open-weight)           | Gemini, Anthropic Claude, OpenAI              |
| LLM — judge (eval)          | **NVIDIA NIM** `nvidia/llama-3.3-nemotron-super-49b-v1` (reasoning-tuned, ≥ generator) | Gemini             |
| Embedding                   | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5` (1024d)              | Gemini `gemini-embedding-001`                 |
| Reranker                    | NVIDIA NeMo Retriever `nvidia/rerank-qa-mistral-4b`                  | —                                             |
| Vector + lexical store      | **Neon Postgres + pgvector + tsvector FTS**                          | —                                             |
| Agent                       | hand-written ReAct + LangGraph rewrite (Wave 4)                      | —                                             |
| Eval                        | hand-written metrics (recall@k / MRR / nDCG + LLM judge)             | —                                             |
| Tracing                     | Langfuse Cloud                                                       | —                                             |
| Output validation           | pydantic + citation ID / quote integrity checks                      | —                                             |
| Guardrails (Wave 6)         | deterministic injection / PII / output screens + optional NVIDIA NemoGuard content-safety | —                              |
| MCP (Wave 6)                | official `mcp` Python SDK — stdio + streamable HTTP server           | —                                             |
| API / UI                    | FastAPI (SSE + JSON) + Next.js 16 / React 19                         | Streamlit (legacy VPS UI)                      |
| Async ingestion             | persisted Neon job state + Upstash QStash delivery                   | CLI ingestion runs synchronously              |
| Deployment                  | two Vercel projects (`backend` + `frontend`)                         | Docker Compose on a VPS                        |

Provider switching is environment-controlled (`LLM_PROVIDER`,
`LLM_JUDGE_PROVIDER`, `EMBEDDING_PROVIDER`, `RERANKER_PROVIDER`) and implemented
as single-file `if/elif` dispatch. NVIDIA NIM is the primary for both generation
and judging; Gemini / Anthropic / OpenAI are optional alternatives. The judge runs a stronger
model than the generator (`nemotron-super-49b`, reasoning/RL-tuned, ≥ the
`llama-3.3-70b` generator) at temperature 0 so its verdicts stay trustworthy.
Model choices are eval-driven: `llama-4-maverick` was rejected as generator (it
over-reasoned and broke the strict-JSON answer contract on hard numeric items),
and `deepseek-v4-pro`, though more capable, free-tier 429-throttles too hard to
judge a full eval run.

## Quick start

### Prerequisites

- Python 3.11 or 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node.js 20.19 or newer and npm
- PostgreSQL with pgvector (the production deployment uses Neon)
- A real contact email for SEC EDGAR and an NVIDIA API key

### Backend and CLI

```bash
git clone https://github.com/RealSerendipity/FinRAG.git
cd FinRAG

cp backend/.env.example .env
# Set at least EDGAR_USER_AGENT, DATABASE_URL, and NVIDIA_API_KEY.
# The template already selects NVIDIA for generation, embeddings, and reranking.

uv --directory backend sync --group dev
uv --directory backend run pytest

# The first business command bootstraps the database schema automatically.
uv --directory backend run finrag ingest --tickers AAPL --year 2024
uv --directory backend run finrag ask --ticker AAPL --year 2024 "What was Apple's R&D expense?"
```

Gemini, Anthropic, OpenAI, Langfuse, Tavily, and NemoGuard are optional. Install
the `full` extra only for the legacy Streamlit UI or the optional Docling
experiment:

```bash
uv --directory backend sync --extra full --group dev
```

### Local FastAPI + Next.js

Set a non-empty `API_TOKEN` in the root `.env`. Then copy the frontend template
and set `FINRAG_API_TOKEN` to the same value:

```bash
cp frontend/.env.example frontend/.env.local
# frontend/.env.local:
# FINRAG_API_URL=http://127.0.0.1:8000
# FINRAG_API_TOKEN=<same value as API_TOKEN in .env>
npm --prefix frontend ci
```

Run both services from the repository root:

```bash
# Terminal 1: FastAPI
uv --directory backend run uvicorn src.api:app --host 0.0.0.0 --port 8000

# Terminal 2: Next.js
npm --prefix frontend run dev  # open http://localhost:3000
```

The Next.js UI provides a **RAG / Agent mode toggle** (single-shot cited answer
vs. a multi-step tool-using agent) and a durable **ingest panel**. Route handlers
proxy browser requests to FastAPI, so credentials stay on the server.

The local RAG and Agent modes work with the setup above. The web ingest panel
publishes background work through QStash, so it additionally requires
`QSTASH_TOKEN`, both QStash signing keys, and a publicly reachable
`FINRAG_PUBLIC_API_URL`. For a completely local setup, use the CLI to ingest.

| Agent mode — running | Agent mode — multi-step tool trace |
| :---: | :---: |
| ![finrag agent running](docs/agent-running.png) | ![finrag agent result](docs/agent-result.png) |

*Agent mode on a multi-step question ("how did Apple's R&D-to-revenue ratio change
FY2023 → FY2024?"): the ReAct loop calls `lookup_metric` (SEC XBRL) for R&D and
revenue across both years, then `calculator`, and shows the full reasoning trace.*

Run the current checks from the repository root:

```bash
uv --directory backend run pytest
npm --prefix frontend run test:run
npm --prefix frontend run lint
npm --prefix frontend run build
```

### Production deployment

| Service | Public URL |
| --- | --- |
| Next.js frontend | [https://www.realserendipity.org/finrag/](https://www.realserendipity.org/finrag/) |
| FastAPI backend | [https://fin-rag-nu.vercel.app](https://fin-rag-nu.vercel.app/) |
| Backend health | [https://fin-rag-nu.vercel.app/health](https://fin-rag-nu.vercel.app/health) |

The same GitHub repository is imported into Vercel twice:

| Vercel project | Root Directory | Configuration |
| --- | --- | --- |
| `fin-rag` | `backend` | FastAPI entrypoint in `backend/pyproject.toml`; function settings in `backend/vercel.json` |
| `finrag-frontend` | `frontend` | Next.js is detected automatically |

Set these frontend production variables:

```dotenv
FINRAG_API_URL=https://fin-rag-nu.vercel.app
FINRAG_API_TOKEN=<same value as backend API_TOKEN>
```

The backend needs the variables from `backend/.env.example` for the selected
providers, Neon, and auth. For asynchronous web ingestion, also set
`FINRAG_PUBLIC_API_URL=https://fin-rag-nu.vercel.app` and connect Upstash QStash;
the integration injects `QSTASH_URL`, `QSTASH_TOKEN`,
`QSTASH_CURRENT_SIGNING_KEY`, and `QSTASH_NEXT_SIGNING_KEY`. Redeploy a service
after changing its environment variables.

### Docker / VPS

The legacy Streamlit UI remains available for the single-container VPS path.
The image reads the root `.env`, runs FastAPI internally on port 8000, and exposes
only Streamlit on port 8501:

```bash
docker compose -f infra/compose.yaml up --build
# open http://localhost:8501
```

Put port 8501 behind your own TLS reverse proxy for public VPS use. As with the
local web ingest panel, asynchronous ingestion needs QStash and a public callback
URL; CLI ingestion does not.

### Direct API

```bash
curl http://127.0.0.1:8000/health
curl -N -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer replace-with-your-api-token' \
  -d '{"question":"What was Apple total net sales in fiscal 2024?","ticker":"AAPL","year":2024}'
```

Routes: `GET /health`, `POST /ask` (SSE: status → answer → done, with heartbeat
pings), `POST /agent` (ReAct, JSON), `POST /ingest` (returns **202 + job_id**),
and `GET /ingest/{job_id}` (poll status/results). Each `/ask` and `/agent`
response includes latency, token usage, a model-aware `$/query` estimate, and,
when `LANGFUSE_*` is configured, a fail-open `trace_url`. Unexpected failures
return a stable `internal_error` code while details remain in server logs.

**Authentication.** Set `API_TOKEN` to protect `/ask`, `/agent`, `/ingest`, and
`/ingest/{job_id}` with `Authorization: Bearer <token>`; `/health` remains
public. `API_ROOT_PATH` supports a reverse-proxy path prefix. For public
exposure, set `RATE_LIMIT_ENABLED=1`: `/ask` is limited to 10/minute, `/agent`
to 3/minute, and `/ingest` to 2/hour. Both Next.js and Streamlit call FastAPI
server-side through `FINRAG_API_URL` + `FINRAG_API_TOKEN`, so the API token never
reaches the browser.

## Security & MCP (Wave 6)

**Guardrails.** [`backend/src/guardrails.py`](backend/src/guardrails.py) wraps the RAG and agent paths
in a defense-in-depth filter set, on by default (`GUARDRAILS_ENABLED=1`):

- `screen_input` — refuse prompt-injection / jailbreak / system-prompt-extraction
  attempts *before* the model runs. Deterministic signatures (always on, no network),
  plus an optional [NVIDIA NemoGuard](https://build.nvidia.com/nvidia/llama-3_1-nemoguard-8b-content-safety)
  content-safety check (`NEMOGUARD_ENABLED=1`) for genuinely harmful content.
- `screen_context` / `screen_observation` — drop retrieved filing chunks carrying
  *indirect* injection ("ignore the user and …") before generation, and withhold
  agent tool observations (retrieved excerpts, web-search snippets) that carry the
  same signatures — so a poisoned snippet can't hijack the answer or the loop.
  Dropped chunks are logged and traced, never silently discarded.
- `validate_output` / `redact_pii` — run on every `ask`/`agent` answer before it is
  returned: withhold an answer that echoes the prompt/configuration, then strip
  emails / SSNs / card numbers (Luhn-checked) / phones from the text.

The signatures target attack *phrasing*, not finance vocabulary, so benign filing
questions pass untouched (false-positive-free, verified in `backend/tests/test_wave6.py`).
NemoGuard rates content *harm*, not injection, so it augments — never replaces — the
signatures, and always fails open to them.

**Red team.** [`backend/eval/red_team.jsonl`](backend/eval/red_team.jsonl) holds adversarial prompts
across five classes (direct jailbreak, system-prompt extraction, citation manipulation,
indirect injection via a planted chunk, and Chinese-language attacks). The harness runs
each one with defenses off vs on and reports attack-success-rate before/after — success
is detected deterministically via a canary, so the number is reproducible:

```bash
uv --directory backend run python eval/run_red_team.py        # → backend/eval/reports/wave_6.md (+ raw run)
```

Results — including which layer stops each attack — are in
[`backend/eval/reports/wave_6.md`](backend/eval/reports/wave_6.md).

**Use finrag as an MCP tool.** [`backend/src/mcp_server.py`](backend/src/mcp_server.py) exposes finrag
over the [Model Context Protocol](https://modelcontextprotocol.io) (official `mcp` SDK):
`ask_filings` (cited RAG), `research_agent` (multi-step ReAct), and the Wave 4 toolset
(`retrieve_filing`, `lookup_metric`, `compare_companies`, `web_search`, `calculator`).
Two transports, chosen with `FINRAG_MCP_TRANSPORT`:

*Local (stdio)* — for an MCP client running on the same machine, which launches the
server as a subprocess. On the command line:

```bash
claude mcp add finrag -- uv --directory backend run python -m src.mcp_server
```

or as a config entry (`.mcp.json`, `claude_desktop_config.json`, Cursor, …):

```json
{
  "mcpServers": {
    "finrag": {
      "command": "uv",
      "args": ["--directory", "backend", "run", "python", "-m", "src.mcp_server"],
      "cwd": "/absolute/path/to/finrag"
    }
  }
}
```

*Remote (Streamable HTTP)* — to expose finrag as a **network service** any remote MCP
client can reach. It runs stateless (proxy/tunnel-friendly). When `MCP_TOKEN` is
set, requests must send `Authorization: Bearer <MCP_TOKEN>`; without it the server
starts unauthenticated and prints a warning. Always set it for network exposure.
Run the service bound to localhost and front it with your reverse proxy / tunnel
(TLS + the same `MCP_TOKEN`), like the web demo:

```bash
MCP_TOKEN=your-secret FINRAG_MCP_TRANSPORT=http uv --directory backend run python -m src.mcp_server
# → serves Streamable HTTP at http://127.0.0.1:8200/mcp
```

Then point any HTTP-capable MCP client at the public `/mcp` URL with the bearer header.
On the command line:

```bash
claude mcp add --transport http finrag https://your-domain/mcp \
  --header "Authorization: Bearer your-secret"
```

or as a config entry (`.mcp.json`, Cursor, VS Code, …):

```json
{
  "mcpServers": {
    "finrag": {
      "type": "http",
      "url": "https://your-domain/mcp",
      "headers": { "Authorization": "Bearer your-secret" }
    }
  }
}
```

Asking "What was AAPL's revenue in FY2024?" calls finrag's `ask_filings`
and answers with citations to the SEC source. The same guardrails apply across the
whole MCP surface: `ask_filings` / `research_agent` inherit them from the RAG/agent
paths, and the directly exposed Wave 4 tools screen their string inputs before
running and their outputs like agent observations (a poisoned excerpt is withheld,
not returned). For network exposure, set `FINRAG_MCP_ALLOWED_HOSTS` (host allow-list)
together with `MCP_TOKEN` (bearer auth) — defence in depth on top of your proxy's TLS.

### Verify it works

```bash
# 1) Red team — produces ASR before/after into backend/eval/reports/wave_6.md (+ raw run).
#    Blank LANGFUSE_* for batch runs (tracing isn't needed and can stall the first call).
LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= uv --directory backend run python -u eval/run_red_team.py
#    → SUMMARY {"asr_before": ~0.29, "asr_after": ~0.07}

# 2) MCP server — verify tools/list with the official inspector (needs npx).
npx @modelcontextprotocol/inspector --cli uv --directory backend run python -m src.mcp_server --method tools/list
#    → JSON listing 7 tools (ask_filings, research_agent + the 5 Wave 4 tools).
#    Drop --cli/--method for the browser UI to call them interactively.

# 3) Add the server to any MCP client (config above), ask an AAPL question
#    → answered via finrag's ask_filings, with citations to the SEC filing.

# 4) Guardrails — zero false positives on benign queries + attacks blocked (offline).
uv --directory backend run python -m pytest tests/test_wave6.py -q     # guardrails + MCP tests pass
```

Guardrails are on by default, so `finrag ask`, `/agent`, and the MCP tools are already
protected in real use: an injection prompt gets a fixed refusal before any model call
(`GUARDRAILS_ENABLED=0` disables them to measure the undefended baseline).

## Chunking strategies

Chunking is configurable at ingest time — pick one per run with `--chunk-strategy`
or the `CHUNK_STRATEGY` env var (default `fixed`). It only changes how a filing is
split before embedding; retrieval and answering are unchanged. An unknown value
fails fast (before any EDGAR/embedding work).

```bash
# choose per run with the CLI flag:
uv --directory backend run finrag ingest --tickers AAPL --year 2024 --chunk-strategy section

# or set the default in .env (CHUNK_STRATEGY=section) and run normally:
uv --directory backend run finrag ingest --tickers AAPL --year 2024
```

| Strategy | What it does |
| --- | --- |
| `fixed` (default) | Paragraph-packed token windows (~300 cl100k tokens; oversized paragraphs split with overlap). |
| `sentence_window` | Overlapping windows of N sentences — keeps clauses intact. |
| `section` | Splits at 10-K structural headings (Item / Part) and prefixes each chunk with its section heading. |
| `parent_doc` | Embeds a small child for precise retrieval, stores the larger parent block in metadata; `ask()` feeds the parent to the LLM as context. |

On the AAPL 10-K eval corpus `fixed` wins — the corpus is small and number/table-dense, so finer chunking inflates the recall denominator (see [`backend/eval/reports/wave_3a.md`](backend/eval/reports/wave_3a.md) and [`wave_3g.md`](backend/eval/reports/wave_3g.md)). The alternatives are kept because the best strategy is corpus-dependent; switch and re-measure on a new corpus.

### Adding a new chunking strategy

The strategy name has a single source of truth (`VALID_CHUNK_STRATEGIES` in `backend/src/ingest.py`), so adding one is a small, local change:

1. Write a `chunk_<name>(text, ...) -> list[str]` in `backend/src/ingest.py` (or `-> list[tuple[str, str]]` if it needs parent context).
2. Add `"<name>"` to `VALID_CHUNK_STRATEGIES` and a branch in `build_chunks()` returning `list[tuple[str, dict]]` — put any generation-time context (e.g. a parent block) in the `metadata` dict.
3. If you stored `metadata["parent_text"]`, generation already uses it (`rag._context_text` prefers it); nothing else to wire.
4. The `CHUNK_STRATEGY` env var, the `--chunk-strategy` flag, and fail-fast validation all pick the name up automatically from `VALID_CHUNK_STRATEGIES`.
5. Add a unit test in `backend/tests/test_wave3.py` and A/B it with an `backend/experiments/wave3_*.py` script against `backend/eval/run_eval.py`.

## Monorepo layout

```
frontend/
  app/                # Next.js pages and fixed /api proxy Route Handlers
  components/         # bilingual RAG, Agent, health, and ingest UI
  lib/                # i18n, SSE parser, types, and server-only FastAPI client
  package.json
  package-lock.json
backend/
  src/
    api.py            # FastAPI routes and SSE
    rag.py            # retrieval-augmented answer flow
    agent.py          # hand-written ReAct loop
    ingest.py         # filing ingestion pipeline
    ingest_jobs.py    # durable ingest job state
    qstash_queue.py   # QStash publish and signature verification
    clients/          # provider clients
    financial/        # SEC filing and XBRL support
    tools/            # agent tools
  prompts/           # versioned prompt files (answer_v*, react_v1)
  sql/               # runtime schema migrations
  data/              # raw / processed / fixtures
  eval/              # evaluation suites, metrics, and reports
  experiments/       # retrieval ablation scripts
  tests/             # pytest suites
  pyproject.toml
  uv.lock
  vercel.json        # backend Vercel project configuration
infra/
  Dockerfile
  compose.yaml
  entrypoint.sh
docs/                # documentation assets
README.md            # English documentation (kept at repository root)
README.zh-CN.md      # Chinese documentation (kept at repository root)
```

## License

[MIT](LICENSE). This is a personal learning / portfolio project and is provided
as-is, without warranty.
