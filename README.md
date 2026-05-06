# finrag

[English](README.md) | [简体中文](README.zh-CN.md)

Retrieval + agent system over SEC filings (10-K / 10-Q / earnings calls). A
hands-on LLM application engineering project for financial research workflows,
structured answers, citations, evaluation, and deployable AI product surfaces.

## Overview

finrag is a portfolio-grade financial RAG project for answering investment
research questions over company filings with traceable citations. The project
is designed to grow from a simple cloud-API-backed RAG baseline into an
evaluated, observable, agentic system with retrieval experiments, financial
tools, public demo surfaces, and MCP integration.

The target user is a developer, analyst, or interviewer who wants to inspect how
the system ingests filings, retrieves relevant evidence, validates structured
answers, measures quality, and exposes the workflow through CLI, API, UI, and
agent tools.

## Roadmap

| Wave | Title | Status | Headline metric |
|---|---|---|---|
| 0 | Foundation (closed LLM dispatch, scaffolding) | ✅ shipped (live verify pending) | — |
| 1a | Postgres + pgvector schema + NVIDIA embedding provider | ⏳ next | schema migration idempotent; `embed()` returns 768d vectors |
| 1b | Dense retrieval + cited answer (pydantic) over local fixture | ⏳ | structured `Answer` with valid citations |
| 1c | EDGAR ingestion + CLI driver | ⏳ | `finrag ingest` + `finrag ask` end-to-end |
| 1d | NVIDIA NIM as cloud open-weight provider | ⏳ | `LLM_PROVIDER=nvidia` round-trip |
| 1.5 | Mini-eval (5–10 hand-graded items) | ⏳ | retrieval hit-rate, citation validity |
| 2 | Eval harness (30–50 curated items) | ⏳ | recall@k, MRR, nDCG, faithfulness |
| 3 | Retrieval quality (chunking / table-aware / hybrid / rerank / query rewrite) | ⏳ | recall@10 ablation table |
| 4 | ReAct agent + tools, then LangGraph migration | ⏳ | task success rate |
| 5A | Public demo (FastAPI + Streamlit deployed) | ⏳ | demo URL, citation UI |
| 5B | Observability, cost, streaming, caching | ⏳ | p50 latency, $/query (before/after) |
| 6 | Security & protocols (prompt-injection red team, output guardrails, MCP server) | ⏳ | attack-success-rate ↓ |
| 7 | Extensions & framework comparisons (LlamaIndex / DSPy / CrewAI / Cloudflare edge / CN A-share / memory / self-correct) | ⏳ | per-item resume bullets |

## Stack (cloud APIs only — no local services)

| Layer                       | Primary                                                                 | Backup(s)                                    |
| --------------------------- | ----------------------------------------------------------------------- | -------------------------------------------- |
| LLM (closed)                | Google Gemini (`2.5-flash` / `-pro` / `-flash-lite`)                    | Anthropic Claude, OpenAI                     |
| LLM (open-weight via cloud) | NVIDIA NIM / build.nvidia.com (Llama / Qwen / DeepSeek / Nemotron) — *planned, Wave 1d* | Together, Groq                               |
| Embedding                   | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5` (768d target)           | Gemini `gemini-embedding-001`, Voyage, Cohere |
| Reranker                    | NVIDIA NeMo Retriever `nvidia/nv-rerankqa-mistral-4b-v3`                | Jina `rerank-v2-multilingual`, Cohere         |
| Vector + lexical store      | **Neon Postgres + pgvector + tsvector FTS**                             | Supabase, Aiven                              |
| Agent                       | hand-written ReAct → LangGraph (Wave 4)                                 | LlamaIndex (Wave 7 comparison)               |
| Eval                        | hand-written + ragas; NVIDIA NIM judge after Wave 1d                    | Gemini judge fallback                        |
| Tracing                     | Langfuse Cloud                                                          | —                                            |
| Output validation           | pydantic                                                                | —                                            |
| Guardrails (Wave 6)         | NVIDIA NemoGuard + custom regex/PII                                     | OpenAI Moderation                            |
| MCP (Wave 6)                | official `mcp` Python SDK as server                                     | —                                            |
| API / UI                    | FastAPI + Streamlit                                                     | —                                            |
| Deployment                  | Render / Railway / Fly.io free tier; Cloudflare Worker for edge demo    | —                                            |

Provider switching is environment-controlled (`LLM_PROVIDER`,
`EMBEDDING_PROVIDER`, `RERANKER_PROVIDER`) and implemented as single-file
`if/elif` dispatch.

## Quick start

```bash
uv sync --group dev
cp .env.example .env
# fill in GEMINI_API_KEY at minimum for Wave 0
uv run pytest
```

## Layout

```
src/
  llm.py            # LLM dispatch
  embed.py          # embedding dispatch
  db.py             # Postgres connection + schema bootstrap
  rag.py            # retrieve → prompt → Answer (pydantic)
  retrieve.py       # vector / FTS / hybrid / rerank retrieval
  ingest.py         # parse → split → embed → upsert
  cli.py            # finrag ask / ingest
  financial/        # EDGAR, table extraction, pydantic schemas
  rerank.py         # reranker dispatch
  agent.py          # ReAct loop
  tools/            # financial tools
  api.py            # FastAPI
  ui.py             # Streamlit
  guardrails.py     # input/output filters
  mcp_server.py     # expose tools as MCP server
prompts/            # versioned prompt files
sql/                # schema migrations
eval/               # questions, red-team set, metrics, reports
experiments/        # ablation scripts
edge/               # Cloudflare Worker source
.env.example
pyproject.toml
README.md
README.zh-CN.md
```

## License

Personal learning / portfolio project; not production software.
