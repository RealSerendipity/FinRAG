# finrag

Retrieval + agent system over SEC filings (10-K / 10-Q / earnings calls). A
hands-on LLM application engineering project: every wave ships an independently
useful slice and an updated metric line in the table below.

## Status

See [EXECUTION_PLAN.md](EXECUTION_PLAN.md) for detailed wave plans + DoD.

| Wave | Title | Status | Headline metric | Commit |
|---|---|---|---|---|
| 0 | Foundation (LLM dispatch, scaffolding) | ✅ shipped (live verify pending) | — | `ac0da4e` |
| 1 | Naive RAG baseline + structured output (Postgres + pgvector) | ⏳ next | recall@10, faithfulness | — |
| 2 | Eval harness | ⏳ | retrieval + LLM-judge metrics | — |
| 3 | Retrieval quality (chunking / table-aware / hybrid / rerank / query rewrite) | ⏳ | recall@10 ablation table | — |
| 4 | ReAct agent + tools, then LangGraph migration | ⏳ | task success rate | — |
| 5 | Production hardening (caching, streaming, tracing, FastAPI/Streamlit, cloud deploy) | ⏳ | p50 latency, $/query | — |
| 6 | Security & protocols (prompt-injection red team, output guardrails, MCP server) | ⏳ | attack-success-rate ↓ | — |
| 7 | Extensions & framework comparisons (LlamaIndex / DSPy / CrewAI / Cloudflare edge / CN A-share / memory / self-correct) | ⏳ | per-item resume bullets | — |

## Stack (cloud APIs only — no local services)

| Layer | Primary | Backup(s) |
|---|---|---|
| LLM (closed) | Google Gemini (`2.5-flash` / `-pro` / `-flash-lite`) | Anthropic Claude, OpenAI |
| LLM (open-weight via cloud) | OpenRouter (Llama 3.3 / Qwen / DeepSeek free tier) | Together, Groq |
| Embedding | Gemini `gemini-embedding-001` (768d) | Voyage `voyage-3-large`, Cohere `embed-v4.0` |
| Reranker | Jina `rerank-v2-multilingual` | Cohere `rerank-v3.5` |
| Vector + lexical store | **Neon Postgres + pgvector + tsvector FTS** | Supabase, Aiven |
| Agent | hand-written ReAct → LangGraph (Wave 4) | LlamaIndex (Wave 7 comparison) |
| Eval | hand-written + ragas | — |
| Tracing | Langfuse Cloud | — |
| Output validation | pydantic | — |
| Guardrails (Wave 6) | OpenAI Moderation + custom regex/PII | Llama Guard via OpenRouter |
| MCP (Wave 6) | official `mcp` Python SDK as server | — |
| API / UI | FastAPI + Streamlit | — |
| Deployment | Render / Railway / Fly.io free tier; Cloudflare Worker for edge demo | — |

Provider switching is environment-controlled (`LLM_PROVIDER`,
`EMBEDDING_PROVIDER`, `RERANKER_PROVIDER`) and implemented as single-file
`if/elif` dispatch. See [PROJECT_RULES.md](PROJECT_RULES.md) for the engineering
discipline this project commits to.

## Quick start

```bash
uv sync --extra dev
cp .env.example .env
# fill in GEMINI_API_KEY at minimum
uv run pytest
```

## Layout

```
src/
  config.py         # env-driven settings
  llm.py            # 4-provider chat dispatch (Gemini / Anthropic / OpenAI / OpenRouter)
  embed.py          # 3-provider embedding dispatch        (Wave 1)
  rerank.py         # 2-provider reranker dispatch         (Wave 3)
  db.py             # psycopg + schema bootstrap           (Wave 1)
  ingest.py         # parse → split → embed → upsert       (Wave 1)
  retrieve.py       # vector / FTS / hybrid / rerank       (Wave 1, expanded Wave 3)
  rag.py            # retrieve → prompt → Answer (pydantic) (Wave 1)
  agent.py          # ReAct loop                           (Wave 4)
  tools/            # 5 financial tools                    (Wave 4)
  guardrails.py     # input/output filters                 (Wave 6)
  mcp_server.py     # expose tools as MCP server           (Wave 6)
  financial/        # domain-specific (EDGAR, table extract, pydantic schemas)
  api.py            # FastAPI                              (Wave 5)
  ui.py             # Streamlit                            (Wave 5)
  cli.py
prompts/            # versioned prompt files
sql/                # schema migrations                    (Wave 1)
eval/               # questions, red-team set, metrics, reports
experiments/        # ablation scripts                     (Wave 3+)
edge/               # Cloudflare Worker source             (Wave 7)
tests/
```

## License

Personal learning / portfolio project; not production software.
