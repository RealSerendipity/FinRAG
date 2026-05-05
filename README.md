# finrag

Retrieval + agent system over SEC filings (10-K / 10-Q / earnings calls). A
hands-on LLM application engineering project: every wave ships an independently
useful slice and an updated metric line in the table below.

## Status

**Wave 0 — Foundation**

| Wave | Title | Status | Headline metric | Commit |
|---|---|---|---|---|
| 0 | Foundation (LLM dispatch, scaffolding) | ✅ in progress | — | — |
| 1 | Naive RAG baseline over 10-K | ⏳ next | recall@10, faithfulness | — |
| 2 | Eval harness | ⏳ | retrieval + LLM-judge metrics | — |
| 3 | Retrieval quality (chunking / hybrid / rerank / query rewrite) | ⏳ | recall@10 ablation table | — |
| 4 | ReAct agent + tools | ⏳ | task success rate | — |
| 5 | Production hardening (caching, streaming, tracing, deploy) | ⏳ | p50 latency, $/query | — |
| 6 | Advanced (CN A-share, report generation, self-correction) | ⏳ | — | — |

## Stack (cloud APIs only — no local services)

| Layer | Primary | Backup(s) |
|---|---|---|
| LLM | Google Gemini (`gemini-2.5-flash` / `-pro` / `-flash-lite`) | Anthropic Claude, OpenAI |
| Embedding | Gemini `gemini-embedding-001` | Voyage AI, Cohere |
| Reranker | Jina Rerank | Cohere Rerank |
| Vector store | Chroma (persistent file, embedded) | Pinecone Free / Qdrant Cloud Free |
| Lexical | `rank_bm25` | — |
| Agent | hand-written ReAct → LangGraph (Wave 4) | — |
| Eval | hand-written + ragas | — |
| Tracing | Langfuse Cloud | — |
| API / UI | FastAPI + Streamlit | — |
| Deployment | Render / Railway / Fly.io free tier (Wave 5) | — |

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
  llm.py            # 3-provider chat dispatch
  ingest.py         # parse + chunk + embed       (Wave 1)
  retrieve.py       # search + rerank             (Wave 1, expanded Wave 3)
  rag.py            # retrieve → prompt → answer  (Wave 1)
  agent.py          # ReAct loop                  (Wave 4)
  tools/            # agent tools                 (Wave 4)
  financial/        # domain-specific (EDGAR, table extract, schemas)
  api.py            # FastAPI                     (Wave 5)
  ui.py             # Streamlit                   (Wave 5)
  cli.py
prompts/            # versioned prompt files
eval/               # questions, metrics, reports
experiments/        # ablation scripts
tests/
```

## License

Personal learning / portfolio project; not production software.
