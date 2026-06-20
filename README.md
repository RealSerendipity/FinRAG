# FinRAG

[English](README.md) | [简体中文](README.zh-CN.md)

Retrieval + agent system over SEC EDGAR filings (10-K / 10-Q / 8-K / 20-F / DEF 14A). A
hands-on LLM application engineering project for financial research workflows,
structured answers, citations, evaluation, and deployable AI product surfaces.

## Overview

FinRAG is a portfolio-grade financial RAG project for answering investment
research questions over company filings with traceable citations. The project
is designed to grow from a simple cloud-API-backed RAG baseline into an
evaluated, observable, agentic system with retrieval experiments, financial
tools, public demo surfaces, and MCP integration.

The target user is a developer, analyst, or interviewer who wants to inspect how
the system ingests filings, retrieves relevant evidence, validates structured
answers, measures quality, and exposes the workflow through CLI, API, UI, and
agent tools.

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
retrieval quality. Baseline: [`eval/reports/wave_2.md`](eval/reports/wave_2.md);
winning config: [`eval/reports/wave_3_runeval.md`](eval/reports/wave_3_runeval.md);
per-step ablations: [`eval/reports/wave_3{a..f}.md`](eval/reports/) (also in the
[ablation table](#wave-3-retrieval-ablations) below).

## Roadmap

| Wave | Title                                                                                                                  | Status    | Headline metric                                              |
| ---- | ---------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------------------------------------------ |
| 0    | Foundation (closed LLM dispatch, scaffolding)                                                                          | ✅ shipped | —                                                            |
| 1a   | Postgres + pgvector schema + NVIDIA embedding provider(Asymmetric model for RAG)                                       | ✅ shipped | schema migration idempotent; `embed()` returns 1024d vectors |
| 1b   | Dense retrieval + cited answer (pydantic) over local fixture                                                           | ✅ shipped | structured `Answer` with valid citations                     |
| 1c   | EDGAR ingestion + CLI driver                                                                                           | ✅ shipped | `finrag ingest` + `finrag ask` end-to-end                    |
| 1d   | NVIDIA NIM as cloud open-weight provider                                                                               | ✅ shipped | `LLM_PROVIDER=nvidia` round-trip                             |
| 1.5  | Mini-eval over real AAPL FY2024 10-K (n=7, 6 positive + 1 insufficient) + prompt `v1.1` (insufficient-context returned as JSON, not bare text) | ✅ shipped | hit@5 / recall@5 / MRR / nDCG@5 / structural citation validity / LLM-judge faithfulness — numbers in [`eval/reports/wave1_5_mini_eval.md`](eval/reports/wave1_5_mini_eval.md) |
| 2    | Eval harness (38 curated items × 5 categories, NIM judge + Gemini fallback)                                            | ✅ shipped | recall@10 0.80 / MRR 0.64 / nDCG@10 0.65 / citation validity 0.82 / faithfulness 0.84 / correctness 0.84 — details in [`eval/reports/wave_2.md`](eval/reports/wave_2.md) |
| 3    | Retrieval quality (chunking / table-aware / hybrid / rerank / query rewrite)                                           | ✅ shipped | recall@10 0.72 → **0.885** (hybrid + rerank); see [ablation table](#wave-3-retrieval-ablations) |
| 4    | Hand-written ReAct agent + 5 tools, then LangGraph rewrite                                                              | ✅ shipped | task success **0.94** (17/18) · tool-call accuracy 1.00 · avg 3.0 steps — [`eval/reports/wave_4.md`](eval/reports/wave_4.md), A/B in [`wave_4_langgraph_compare.md`](eval/reports/wave_4_langgraph_compare.md) |
| 5A   | Public demo (FastAPI + Streamlit deployed)                                                                             | ⏳         | demo URL, citation UI                                        |
| 5B   | Observability, cost, streaming, caching                                                                                | ⏳         | p50 latency, $/query (before/after)                          |
| 6    | Security & protocols (prompt-injection red team, output guardrails, MCP server)                                        | ⏳         | attack-success-rate ↓                                        |
| 7    | Extensions & framework comparisons (LlamaIndex / DSPy / CrewAI / Cloudflare edge / CN A-share / memory / self-correct) | ⏳         | per-item resume bullets                                      |

### Wave 3 retrieval ablations

Each step is an A/B over the 38-item eval set (retrieval metrics are
LLM-independent, so they are measured directly from `retrieve()` output). Full
methodology and per-category tables in `eval/reports/wave_3{a..f}.md`; each
`experiments/wave3_*.py` reproduces its row.

| Step | Change | Result (vs its baseline) | Shipped? |
| ---- | ------ | ------------------------ | -------- |
| 3a | chunking: fixed vs sentence-window vs parent-doc | recall@10 **fixed 0.722** > parent_doc 0.515 > sentence_window 0.247 | fixed (semantic splits shred tables) |
| 3b | table-aware ingestion (Docling) | numeric+table recall@10 0.738→0.671, **MRR +0.042** | no — extraction lossy on SEC HTML; mixed |
| 3c | hybrid pgvector + tsvector RRF | recall@10 0.722→**0.753** (+0.031), MRR +0.038 | ✅ `RETRIEVAL_MODE=hybrid` |
| 3d | cross-encoder rerank (top-50→10) | recall@10 0.753→**0.885**, MRR 0.681→0.801, nDCG→0.798 | ✅ `RERANK_ENABLED=1` (biggest win) |
| 3e | query rewriting (under-specified queries) | HyDE recall@10 0.622→**0.676** (+0.054); multi-query −0.017 | configurable `QUERY_REWRITE=multi_query\|hyde`; default `none` |
| 3f | embedding: NVIDIA vs Gemini | Gemini recall@10 0.722→**0.788** (+0.066), MRR +0.190 — but 3× dim/cost | no — keep index-matched 1024-d NVIDIA |

**Shipped default: fixed chunking + hybrid RRF + rerank** → recall@10 **0.722 → 0.885**, MRR **0.643 → 0.801**, nDCG@10 **0.610 → 0.798** (dense baseline → winning config; reranker `nvidia/rerank-qa-mistral-4b`, the model served on this account in place of the plan's `-v3`).

**Why `QUERY_REWRITE=none` by default (3e):** against the raw baseline, HyDE trades top-rank precision (MRR −0.038 / nDCG −0.035 / recall@5 −0.047) for coverage (recall@10 +0.054 / hit@5 +0.083 / hit@10 +0.055), and multi-query is roughly neutral — neither is a clean win. The shipped path also keeps ticker/period metadata filtering, which already disambiguates the vague queries rewriting targets, and each rewrite adds an LLM call. So it ships off but stays a per-call toggle. Full per-metric breakdown and the under-specified test setup: [`eval/reports/wave_3e.md`](eval/reports/wave_3e.md).

## Wave 4 — ReAct agent + tools

A hand-written ReAct loop ([`src/agent.py`](src/agent.py)) — Thought → Action →
Observation, no agent framework — over five tools:

| Tool | Source | Use |
| ---- | ------ | --- |
| `retrieve_filing` | hybrid + rerank retriever (Wave 3) | narrative / qualitative facts in ingested filings |
| `lookup_metric` | SEC XBRL `companyconcept` API | one audited annual figure (no RAG) |
| `compare_companies` | SEC XBRL | the same metric across companies, side by side |
| `calculator` | AST eval (no `eval`) | ratios, % change, sums |
| `web_search` | Tavily (optional) | out-of-corpus facts |

The split is deliberate: numeric questions hit structured XBRL, not chunked prose.
Every run logs a replayable JSONL trace to `runs/<id>.jsonl`; the agent keeps a
small session memory (last N Q/A). Over an 18-task multi-step suite
([`eval/agent_questions.jsonl`](eval/agent_questions.jsonl)):

| Metric | Result |
| ------ | ------ |
| task success (LLM-judge correctness) | **0.94** (17/18; the one miss is a stale ground-truth figure, not an agent error) |
| tool-call accuracy | **1.00** |
| average steps / task | **3.0** (≤ 6 target) |

The same loop is rewritten on LangGraph ([`src/agent_lg.py`](src/agent_lg.py)) as a
two-node `StateGraph`; both produce identical tool sequences — see the A/B in
[`eval/reports/wave_4_langgraph_compare.md`](eval/reports/wave_4_langgraph_compare.md).
Run it: `uv run python -m src.agent "..."` or `uv run python eval/run_eval.py --suite agent`.

> **Design choice — text ReAct vs native tool-calling.** This loop is deliberately
> *text-based*: the model emits `Thought / Action / Action Input (JSON) / Final
> Answer` as plain text and the loop **terminates on `Final Answer:`**, not on the
> API's `tool_calls` field. The cost is depending on the model to honor the format
> (handled with single-arg coercion, a same-line lookahead, and client-side
> truncation at `\nObservation:`); the payoff is that any chat model works with
> **zero code change** — only `LLM_PROVIDER` changes — verified live on both NVIDIA
> and Gemini. Native function-calling is more robust in production (the API
> guarantees structure) but provider-specific; a three-way bench (text /
> LangGraph / native function-calling) is planned as `execution.md` **7.fc**.

## Stack (cloud APIs only — no local services)

| Layer                       | Primary                                                              | Backup(s)                                     |
| --------------------------- | -------------------------------------------------------------------- | --------------------------------------------- |
| LLM — generation            | **NVIDIA NIM** `meta/llama-3.3-70b-instruct` (free open-weight)      | Gemini, Anthropic Claude, OpenAI              |
| LLM — judge (eval)          | **NVIDIA NIM** `nvidia/llama-3.3-nemotron-super-49b-v1` (reasoning-tuned, ≥ generator) | Gemini fallback              |
| Embedding                   | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5` (1024d target)       | Gemini `gemini-embedding-001`, Voyage, Cohere |
| Reranker                    | NVIDIA NeMo Retriever `nvidia/rerank-qa-mistral-4b` (served variant) | Jina `rerank-v2-multilingual`, Cohere         |
| Vector + lexical store      | **Neon Postgres + pgvector + tsvector FTS**                          | Supabase, Aiven                               |
| Agent                       | hand-written ReAct → LangGraph (Wave 4)                              | LlamaIndex (Wave 7 comparison)                |
| Eval                        | hand-written + ragas; NVIDIA NIM judge available                     | Gemini judge fallback                         |
| Tracing                     | Langfuse Cloud                                                       | —                                             |
| Output validation           | pydantic                                                             | —                                             |
| Guardrails (Wave 6)         | NVIDIA NemoGuard + custom regex/PII                                  | OpenAI Moderation                             |
| MCP (Wave 6)                | official `mcp` Python SDK as server                                  | —                                             |
| API / UI                    | FastAPI + Streamlit                                                  | —                                             |
| Deployment                  | Render / Railway / Fly.io free tier; Cloudflare Worker for edge demo | —                                             |

Provider switching is environment-controlled (`LLM_PROVIDER`,
`LLM_JUDGE_PROVIDER`, `EMBEDDING_PROVIDER`, `RERANKER_PROVIDER`) and implemented
as single-file `if/elif` dispatch. NVIDIA NIM is the primary for both generation
and judging; Gemini / Anthropic / OpenAI are backups. The judge runs a stronger
model than the generator (`nemotron-super-49b`, reasoning/RL-tuned, ≥ the
`llama-3.3-70b` generator) at temperature 0 so its verdicts stay trustworthy.
Model choices are eval-driven: `llama-4-maverick` was rejected as generator (it
over-reasoned and broke the strict-JSON answer contract on hard numeric items),
and `deepseek-v4-pro`, though more capable, free-tier 429-throttles too hard to
judge a full eval run.

## Quick start

```bash
uv sync --group dev
cp .env.example .env
# fill in GEMINI_API_KEY + DATABASE_URL + NVIDIA_API_KEY

# Run tests
uv run pytest

# Ingest a filing and ask a question (Wave 1c)
uv run finrag ingest --tickers AAPL --year 2024
uv run finrag ask --ticker AAPL --year 2024 "What was Apple's R&D expense?"
```

## Chunking strategies

Chunking is configurable at ingest time — pick one per run with `--chunk-strategy`
or the `CHUNK_STRATEGY` env var (default `fixed`). It only changes how a filing is
split before embedding; retrieval and answering are unchanged. An unknown value
fails fast (before any EDGAR/embedding work).

```bash
# choose per run with the CLI flag:
uv run finrag ingest --tickers AAPL --year 2024 --chunk-strategy section

# or set the default in .env (CHUNK_STRATEGY=section) and run normally:
uv run finrag ingest --tickers AAPL --year 2024
```

| Strategy | What it does |
| --- | --- |
| `fixed` (default) | Paragraph-packed token windows (~300 cl100k tokens; oversized paragraphs split with overlap). |
| `sentence_window` | Overlapping windows of N sentences — keeps clauses intact. |
| `section` | Splits at 10-K structural headings (Item / Part) and prefixes each chunk with its section heading. |
| `parent_doc` | Embeds a small child for precise retrieval, stores the larger parent block in metadata; `ask()` feeds the parent to the LLM as context. |

On the AAPL 10-K eval corpus `fixed` wins — the corpus is small and number/table-dense, so finer chunking inflates the recall denominator (see [`eval/reports/wave_3a.md`](eval/reports/wave_3a.md) and [`wave_3g.md`](eval/reports/wave_3g.md)). The alternatives are kept because the best strategy is corpus-dependent; switch and re-measure on a new corpus.

### Adding a new chunking strategy

The strategy name has a single source of truth (`VALID_CHUNK_STRATEGIES` in `src/ingest.py`), so adding one is a small, local change:

1. Write a `chunk_<name>(text, ...) -> list[str]` in `src/ingest.py` (or `-> list[(child, parent)]` if it needs parent context).
2. Add `"<name>"` to `VALID_CHUNK_STRATEGIES` and a branch in `build_chunks()` returning `list[(content, metadata)]` — put any generation-time context (e.g. a parent block) in the `metadata` dict.
3. If you stored `metadata["parent_text"]`, generation already uses it (`rag._context_text` prefers it); nothing else to wire.
4. The `CHUNK_STRATEGY` env var, the `--chunk-strategy` flag, and fail-fast validation all pick the name up automatically from `VALID_CHUNK_STRATEGIES`.
5. Add a unit test in `tests/test_wave3.py` and A/B it with an `experiments/wave3_*.py` script against `eval/run_eval.py`.

## Layout

```
src/
  cli.py             # finrag ask / ingest entry point
  config.py          # env-driven provider/model configuration
  llm.py             # LLM provider dispatch (Gemini / Anthropic / OpenAI / NVIDIA)
  embed.py           # embedding dispatch (NVIDIA primary, Gemini for Wave 3f)
  rerank.py          # reranker dispatch (NVIDIA NeMo Retriever)
  db.py              # Postgres connection + schema bootstrap
  ingest.py          # parse → chunk (fixed / sentence-window / section / parent-doc) → embed → upsert
  retrieve.py        # vector / FTS / hybrid (RRF) / rerank retrieval
  query_rewrite.py   # normalize / multi-query / HyDE (Wave 3e)
  rag.py             # retrieve → prompt → Answer (pydantic)
  agent.py           # hand-written ReAct loop + session memory, JSONL traces (Wave 4)
  agent_lg.py        # same loop rewritten on LangGraph (Wave 4 A/B)
  api.py             # FastAPI
  ui.py              # Streamlit
  guardrails.py      # input/output filters
  mcp_server.py      # expose tools as MCP server
  clients/           # thin HTTP clients per provider
    _http.py
    anthropic.py
    gemini.py
    openai.py
    nvidia.py
    edgar.py
  financial/         # EDGAR fetch + pydantic schemas + table extraction
    edgar.py
    schemas.py
    table_extract.py # Docling table-aware extraction (Wave 3b)
  tools/             # agent tools (Wave 4): spec + registry, and one file per concern
    spec.py          #   Tool dataclass (shared, avoids an import cycle)
    calculator.py    #   safe arithmetic (AST, no eval)
    retrieve_filing.py #  semantic search over ingested filing text
    xbrl.py          #   lookup_metric + compare_companies via SEC XBRL
    web_search.py    #   Tavily web search (optional; needs TAVILY_API_KEY)
prompts/             # versioned prompt files (answer_v*, react_v1)
sql/                 # schema migrations
data/                # raw / processed / fixtures
eval/                # questions, agent suite, metrics, reports
experiments/         # ablation scripts
runs/                # agent run traces, one JSONL per run (gitignored)
tests/               # pytest suites
edge/                # Cloudflare Worker source
.env.example
pyproject.toml
README.md
README.zh-CN.md
```

## License

Personal learning / portfolio project; not production software.
