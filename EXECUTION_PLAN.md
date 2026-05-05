# finrag — Execution Plan

Single source of truth for what gets built when, with explicit Definition of
Done (DoD) per wave. Update this file as waves ship.

For engineering discipline see [PROJECT_RULES.md](PROJECT_RULES.md). For the
public-facing milestone table see [README.md](README.md).

---

## Goals (priority order)

1. **Cover the LLM-application-engineer skill set end-to-end** — data, retrieval,
   agent, eval, production, security, protocols
2. **Portfolio**: every wave commits an independently demoable slice with a
   measurable metric delta worth one resume bullet
3. **Monetization-ready**: real user problem (English filings → multilingual
   answers) + free-tier-only stack + cloud-deployable demo

## Domain

Financial / investment research over US-listed filings (10-K, 10-Q, 8-K,
earnings transcripts). Anchor 5–10 companies × 2–3 fiscal years. Wave 7 may
extend to CN A-share annual reports as a monetization differentiator.

---

## Coverage map vs. [mlabonne/llm-course — The LLM Engineer](https://github.com/mlabonne/llm-course)

| # | Module | Subsection | Wave |
|---|---|---|---|
| 1 | Running LLMs | LLM APIs | 0 |
|   |              | Open-source LLMs (via cloud APIs, no local deploy) | 1 (OpenRouter as 4th provider) |
|   |              | Prompt engineering | 1 / 3 / 5 |
|   |              | Structuring outputs (pydantic / JSON schema) | 1 |
| 2 | Building Vector Storage | Ingesting documents | 1 |
|   |                          | Splitting documents | 3a |
|   |                          | Embedding models | 3 (3-provider ablation) |
|   |                          | Vector databases (Postgres + pgvector) | 1 |
| 3 | RAG | Orchestrators (hand-written + LlamaIndex compare) | 1 / 7 |
|   |     | Retrievers (vector + FTS hybrid) | 1 / 3 |
|   |     | Memory | 7 |
|   |     | Evaluation | 2 |
| 4 | Advanced RAG | Query construction (rewrite + HyDE + text-to-SQL) | 3 / 7 |
|   |              | Tools | 4 |
|   |              | Post-processing (rerank + critic) | 3 / 7 |
|   |              | Program LLMs (DSPy) | 7 |
| 5 | Agents | Agent fundamentals (hand-written ReAct) | 4 |
|   |        | Agent protocols (MCP server) | 6 |
|   |        | Vendor frameworks (LangGraph) | 4 |
|   |        | Other frameworks (CrewAI / Smolagents) | 7 |
| 6 | Inference optimization | Prompt / context caching (application-level) | 5 |
|   |                        | Flash Attention / KV cache internals / spec decoding | **out of scope** (not API-only territory) |
| 7 | Deploying LLMs | Demo deployment (Streamlit) | 5 |
|   |                | Server deployment (FastAPI on Render/Fly) | 5 |
|   |                | Edge deployment (Cloudflare Worker) | 7 |
|   |                | Local deployment | **out of scope** by user choice |
| 8 | Securing LLMs | Prompt hacking (red-team eval) | 6 |
|   |               | Defensive measures (Moderation, PII, Llama Guard) | 6 |
|   |               | Backdoors (training-time) | **out of scope** |

Three subsections are deliberately out of scope. They require either local
inference or model-internal work that conflicts with the API-only project
constraint, and would need a separate companion project (vLLM-based inference
server) to study properly.

---

## Tech stack (updated — all cloud APIs, free tier first)

| Layer | Primary | Backups / alternates |
|---|---|---|
| LLM (closed APIs) | **Google Gemini** (`2.5-flash` / `-pro` / `-flash-lite`) | Anthropic Claude, OpenAI |
| LLM (open-weight via cloud) | **OpenRouter** (Llama 3.3 70B / Qwen 2.5 / DeepSeek-V3 free tier) | Together AI, Groq |
| Embedding | **Gemini `gemini-embedding-001`** (768d) | Voyage `voyage-3-large`, Cohere `embed-v4.0` |
| Reranker | **Jina `jina-reranker-v2-base-multilingual`** | Cohere `rerank-v3.5` |
| Vector + lexical store | **Neon Postgres + pgvector + tsvector FTS** | Supabase, Aiven |
| Agent (Wave 4) | hand-written ReAct → LangGraph | LlamaIndex (Wave 7 comparison) |
| Eval | hand-written + ragas | — |
| Tracing | Langfuse Cloud (free tier) | — |
| Output validation | pydantic | — |
| Guardrails (Wave 6) | OpenAI Moderation API + custom regex/PII | Llama Guard via OpenRouter |
| MCP (Wave 6) | official `mcp` Python SDK as server | — |
| API/UI | FastAPI + Streamlit | — |
| Deploy | Render / Railway / Fly.io free tier; Cloudflare Worker for edge demo | — |

**Why Postgres replaces Chroma**: one cloud DB does both dense (`pgvector` HNSW)
and lexical (`tsvector` GIN) retrieval. We drop the `rank_bm25` library, the
hybrid query becomes a single SQL with CTEs and RRF, and we pick up SQL skills
on the way. Neon's branching feature lets us snapshot the DB per Wave 3
chunking experiment without touching the main branch.

---

## Repo layout (updated)

```
src/
  config.py               # env-driven settings
  llm.py                  # 4-provider chat dispatch (Gemini / Anthropic / OpenAI / OpenRouter)
  embed.py                # 3-provider embedding dispatch                (Wave 1)
  rerank.py               # 2-provider reranker dispatch                 (Wave 3)
  db.py                   # psycopg connection + schema bootstrap        (Wave 1)
  ingest.py               # parse → split → embed → upsert               (Wave 1)
  retrieve.py             # vector / FTS / hybrid / rerank               (Wave 1, expanded 3)
  rag.py                  # retrieve → prompt → answer (pydantic-typed)  (Wave 1)
  agent.py                # ReAct loop                                   (Wave 4)
  tools/                  # 5 financial tools                            (Wave 4)
  guardrails.py           # input/output filters                         (Wave 6)
  mcp_server.py           # expose tools as MCP server                   (Wave 6)
  api.py                  # FastAPI                                      (Wave 5)
  ui.py                   # Streamlit                                    (Wave 5)
  cli.py                  # CLI entry
  financial/
    edgar.py              # EDGAR API + filing fetch                     (Wave 1)
    table_extract.py      # table-aware ingestion                        (Wave 3b)
    schemas.py            # pydantic models for filings/chunks/answers
prompts/                  # versioned prompt files
sql/                      # schema migrations
eval/
  questions.jsonl         # 30–50 hand-curated Q&A
  red_team.jsonl          # adversarial prompts                          (Wave 6)
  metrics.py
  run_eval.py
  reports/                # markdown commits = iteration history
experiments/              # ablation scripts (Wave 3+)
runs/                     # agent traces (gitignored)
tests/
edge/                     # Cloudflare Worker source                     (Wave 7)
```

Explicitly absent (and staying so): `base/`, `factory/`, `providers/`,
`domains/`, `plugins/`, `observability/`, `security/` packages. Single-file
dispatch wins until a file exceeds ~400 lines or one branch sprouts > 5 helpers.

---

## Wave-by-wave plan

### Wave 0 — Foundation ✅ shipped (`ac0da4e`)

**Built:** uv project, ruff/pytest, README + PROJECT_RULES, `src/config.py`,
3-provider LLM dispatch in `src/llm.py` with `LLMResponse(text, usage,
provider, model, raw)`, smoke tests skip-without-key.

**Pending live verification:** user adds `GEMINI_API_KEY` to `.env`, runs
`uv run pytest -k gemini`, confirms a real Gemini call passes. Required before
Wave 1 starts.

---

### Wave 1 — Naive RAG baseline + structured output (~3 days)

**Adds**:
- `src/db.py`: psycopg3 connection, schema bootstrap (run on first import)
- `src/financial/edgar.py`: pull 10-K filings for a hard-coded ticker list
  (start with 5 companies, latest filing each)
- `src/financial/schemas.py`: pydantic models for `Filing`, `Chunk`, `Answer`
- `src/embed.py`: 3-provider dispatch (Gemini / Voyage / Cohere)
- `src/ingest.py`: download → strip-to-text → fixed 1000-token chunks → embed →
  upsert into `chunks`
- `src/retrieve.py`: dense top-k via `embedding <=> $query_vec`, with
  `WHERE ticker = ... AND period = ...` metadata filtering
- `src/rag.py`: retrieve → render prompt → call LLM → return
  `Answer(text, citations: list[Citation])` validated by pydantic; reject if
  citations don't reference real chunk IDs
- `src/llm.py`: add **OpenRouter** as 4th provider (so we can call Llama 3.3,
  Qwen, DeepSeek through one OpenAI-compatible endpoint)
- `src/cli.py`: `finrag ask --ticker AAPL "question"`

**Postgres schema** (`sql/001_init.sql`):
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    filing_type TEXT NOT NULL,
    period TEXT NOT NULL,
    filed_at DATE,
    accession TEXT UNIQUE NOT NULL,
    raw_url TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section TEXT,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    tokens INT,
    embedding VECTOR(768),
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX chunks_doc_idx ON chunks (document_id);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin ON chunks USING GIN (tsv);
CREATE INDEX documents_lookup_idx ON documents (ticker, period);
```

**DoD**:
- `finrag ingest --tickers AAPL,MSFT,NVDA,GOOGL,META --year 2024` populates
  Neon DB (visible row counts in CLI output)
- `finrag ask --ticker AAPL "FY2024 R&D 多少?"` returns a pydantic-validated
  `Answer` with at least one citation pointing to a real chunk
- `pytest` green; tests cover schema migration idempotency + RAG round-trip
  with seeded DB
- Resume bullet: *"End-to-end RAG over SEC 10-K filings on Postgres+pgvector,
  pydantic-validated structured outputs, 4 swappable LLM providers including
  open-weight via OpenRouter."*

---

### Wave 2 — Eval harness ★ critical (~3 days)

**Adds**:
- `eval/questions.jsonl`: 30–50 hand-curated `(question, expected_doc_ids,
  expected_answer, category)` items spanning the 5 question types from the
  domain section (numeric, table, cross-doc, reasoning, consistency)
- `eval/metrics.py`:
  - retrieval: `recall@k`, `mrr`, `ndcg`
  - generation: faithfulness + answer-relevancy via LLM-as-judge (using
    `gemini-2.5-flash-lite` by default)
- `eval/run_eval.py`: one command runs the full eval, writes
  `eval/reports/<timestamp>.md` with per-question breakdown + summary table
- README "Milestones / Metrics" gets its first row populated

**DoD**:
- `python eval/run_eval.py` produces a markdown report committed to
  `eval/reports/`
- README milestone table shows Wave 1 baseline numbers
- Resume bullet: *"Built RAG eval harness (recall@k, MRR, nDCG, faithfulness
  via LLM-judge); regression-tested every change."*

---

### Wave 3 — Retrieval quality ★ ablation showcase (~1 week)

Each step is one commit + one eval report + one row in a README ablation table.

| Step | Change | Expected lift |
|---|---|---|
| 3a | Chunking: fixed → semantic (sentence-window) → hierarchical / parent-doc | recall@10 ↑ |
| 3b | Table-aware ingestion: extract 10-K financial tables (Docling / unstructured) as separate chunks with serialized schema | numeric-question accuracy ↑ |
| 3c | Hybrid search: combine pgvector + tsvector via RRF in a single SQL CTE | recall@10 ↑ |
| 3d | Reranker: Jina `rerank-v2` over top-50 → top-10 | faithfulness ↑, MRR ↑ |
| 3e | Query rewriting: add ticker/year/unit normalization; multi-query expansion; HyDE comparison | recall on under-specified queries ↑ |
| 3f | Embedding ablation: Gemini vs Voyage vs Cohere | (data point, may not lift) |

**Tooling**: each step lives as `experiments/wave3_<letter>_<name>.py`; uses a
Neon DB branch so experiments don't pollute the main branch.

**DoD**:
- README has a 6-row ablation table with metric deltas + commit hashes
- All steps shipped behind feature flags so the final pipeline can A/B
- Resume bullet: *"Improved recall@10 from X to Y and faithfulness from A to B
  through table-aware ingestion, hybrid retrieval, reranking, and query
  rewriting; full ablation report in repo."*

---

### Wave 4 — Agent + tools (~1 week)

**Tools** (`src/tools/`):
- `retrieve_filing(ticker, year, query)`
- `lookup_metric(ticker, metric, period)` — backed by EDGAR Financial Data API
  (XBRL) or our own derived `metrics` table
- `compare_companies(tickers, metric, period)`
- `web_search(query)` — Tavily free tier
- `calculator(expression)`

**Agent**:
- `src/agent.py`: hand-written ReAct loop, full trace JSONL to `runs/<id>.jsonl`
  including each tool call, tool result, intermediate reasoning
- `eval/agent_questions.jsonl`: 15–20 multi-step task questions
- agent metrics: task success rate, tool-call accuracy, mean steps,
  citation-completeness on final answer
- Then re-implement same loop with **LangGraph** (`src/agent_lg.py`); A/B on
  same eval set; record LOC and dev-experience notes in
  `eval/reports/wave4_langgraph_compare.md`

**DoD**:
- ReAct agent achieves measurable success rate on the suite
- LangGraph rewrite passes the same eval; comparison report committed
- Resume bullet: *"Implemented ReAct agent (5 financial tools) from scratch
  with full trace logging, then migrated to LangGraph; benchmarked task-level
  success at X% on Y-task suite."*

---

### Wave 5 — Production hardening + cloud deploy (~1 week)

**Adds**:
- **Prompt / context caching**: Anthropic ephemeral cache on system prompt +
  tool schemas; Gemini explicit `client.caches.create(...)` for the chunked
  filing context. Measure latency / cost delta.
- **Streaming**: server-sent events from FastAPI; Streamlit consumes them
- **Cost tracking**: per-request token + USD estimation table in the eval
  report
- **Tracing**: Langfuse Cloud SDK wrapping `chat()`, `retrieve()`, agent
  steps; every CLI / API call generates a viewable trace
- **API**: `src/api.py` — `POST /ask` (stream), `POST /ingest`, `GET /health`
- **UI**: `src/ui.py` — Streamlit single-page Q&A with citations
- **Deploy**: Render or Fly.io free tier with public URL
  (https://finrag-demo.onrender.com or similar); Neon DB stays free tier;
  Langfuse Cloud free tier

**DoD**:
- Public demo URL works; share-able for resume
- Langfuse dashboard shows traces of last 100 production-style calls
- README has p50 latency + cost-per-query before/after caching
- Resume bullet: *"Deployed FastAPI + Streamlit RAG demo on Render free tier
  with prompt caching (cost X→Y per query, p50 As→Bs) and Langfuse tracing."*

---

### Wave 6 — Security & protocols (~1 week)

**Output guardrails (`src/guardrails.py`)**:
- `screen_input(text)`: OpenAI Moderation API → block on harmful categories;
  also detect direct prompt-injection signatures
- `redact_pii(text)`: regex + simple ML detector for emails, phone numbers,
  SSN-like patterns; applied to traces sent to Langfuse
- `validate_output(answer: Answer)`: pydantic strict + custom citation checks
  (every citation resolves to a real chunk ID with non-zero overlap on quoted
  span)
- Optional defense layer: pass through Llama Guard via OpenRouter for
  high-stakes queries

**Prompt-injection red team**:
- `eval/red_team.jsonl`: 25–30 adversarial prompts across categories
  - direct jailbreak ("ignore prior instructions...")
  - system-prompt extraction
  - citation manipulation ("answer with no citations")
  - **indirect injection** via filing content (we plant a payload in a chunk)
  - cross-language attack (Chinese-language jailbreak)
- `eval/run_red_team.py`: measure attack success rate before defenses; ship
  defenses; re-measure
- Report: `eval/reports/red_team_<timestamp>.md`

**MCP server (`src/mcp_server.py`)**:
- Use the official `mcp` Python SDK to expose all 5 financial tools as an MCP
  server (stdio transport)
- Verifiable via `mcp-inspector` and Claude Desktop / Cursor /
  Claude-Code-as-client
- README gets an "Use finrag as an MCP tool from Claude Desktop" section

**DoD**:
- Attack success rate on red-team set drops from baseline X% to Y% post-defense
- MCP server runs and answers `tools/list` + `tools/call` correctly per
  `mcp-inspector`
- Resume bullets:
  - *"Designed and measured prompt-injection red-team eval (28 adversarial
    prompts, 5 categories) — defense layer reduced attack success from X% to
    Y%."*
  - *"Exposed financial-Q&A toolset via the official Model Context Protocol
    SDK; usable from Claude Desktop and any MCP client."*

---

### Wave 7 — Extensions & framework comparisons (opt-in, pick by resume value)

Each item is independent; ship 2–4 of these depending on time and what
strengthens the resume narrative most.

- **LlamaIndex orchestrator comparison**: re-implement Wave 1 RAG core with
  LlamaIndex; commit `experiments/wave7_llamaindex.py` + comparison report
- **DSPy auto-prompt optimization**: pick one prompt (e.g., the rerank prompt
  or the answer prompt), bootstrap it with DSPy `BootstrapFewShot`, measure
  metric delta on the eval set
- **CrewAI or Smolagents port** of Wave 4 agent; one-page comparison report
- **Cloudflare Worker edge demo** (`edge/worker.ts`): single-file TS worker
  that calls Gemini via fetch, deployed to `*.workers.dev`; demonstrates
  edge-deployment skill without local infra
- **text-to-structured-query**: natural-language → SEC EDGAR Financial Data
  API call (XBRL) for precise numeric questions, bypassing RAG
- **Conversational + episodic memory**: per-session short-term memory, plus
  long-term summarized memory written back to a `memories` table
- **Self-correction critic loop**: critic LLM checks the answer's citations
  and numeric claims; if it flags issues, agent retries with critique
- **Report-generation mode**: `finrag report --ticker AAPL --period FY2024`
  produces a bilingual (EN/CN) markdown deep-dive — the monetization MVP
- **CN A-share annual report support**: Tushare / Akshare data ingestion +
  Chinese-aware chunking; differentiation for the monetization story
- **CI eval gates**: GitHub Action runs `eval/run_eval.py` on every PR, fails
  if recall@10 drops by > 0.02 vs main

**DoD per item**: a commit, a report under `eval/reports/`, and a one-line
resume bullet.

---

## How metrics are tracked

- Each wave's eval run writes `eval/reports/<wave>_<timestamp>.md` with a
  fixed table layout (per-question + per-category summary)
- README's "Milestones / Metrics" table gets a new row at wave end with the
  headline metric and commit hash
- Commit messages on metric-affecting changes carry a one-line delta:
  ```
  Wave 3c: hybrid retrieval — recall@10 0.62→0.74, MRR 0.41→0.51 (eval/reports/3c.md)
  ```

## How to verify the project end-to-end (post Wave 5)

1. `git clone` the repo, set `.env` with `GEMINI_API_KEY` + `DATABASE_URL`
2. `uv sync --extra dev`
3. `finrag ingest --tickers AAPL,MSFT --year 2024`
4. `finrag ask --ticker AAPL "FY2024 R&D 支出"` returns a cited answer
5. `python eval/run_eval.py` reproduces metrics within ±0.02 of the
   committed report
6. The deployed demo URL serves the same query
7. Langfuse trace for that query is viewable in the Langfuse dashboard

## Out-of-scope (and why)

- **Flash Attention / KV cache internals / speculative decoding** — model
  internals; require a separate vLLM/TGI-based companion project
- **True local model deployment** — explicitly excluded by user choice
- **Backdoor research** — training-time attacks belong to the LLM Scientist
  track

---

## Working notes

- Code budget per [PROJECT_RULES.md](PROJECT_RULES.md) §5: < 3000 LOC of
  application code through Wave 6. Wave 7 items are mostly self-contained
  experiments under `experiments/` or `edge/` and are budgeted separately.
- Plan deltas are recorded in this file's git history (`git log
  EXECUTION_PLAN.md`). The original brainstorm lives at
  `~/.claude/plans/rag-copilot-rag-agent-snoopy-goose.md` for archival
  purposes only — this file supersedes it.
