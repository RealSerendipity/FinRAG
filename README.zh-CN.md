# FinRAG

[English](README.md) | [简体中文](README.zh-CN.md)

面向 SEC EDGAR 披露文件（10-K / 10-Q / 8-K / 20-F / DEF 14A）的检索增强与 Agent 系统。
这是一个动手型 LLM 应用工程项目，覆盖金融研究工作流、结构化回答、citation、eval 和可部署的 AI 产品形态。

## 概览

FinRAG 是一个作品集级别的金融 RAG 项目，用于在公司披露文件上回答投研问题，并提供可追溯 citation。
项目目标是从一个基于云 API 的简单 RAG baseline，逐步演进成具备 eval、observability、agent tools、公开 demo 和 MCP 集成的应用系统。

目标读者可以从这个仓库里看到：系统如何 ingest filing、检索证据、校验结构化回答、度量质量，并通过 CLI、API、UI 和 agent tool 暴露完整工作流。

## 路线图

| Wave | 标题                                                                                                                    | 状态    | 核心指标                                     |
| ---- | --------------------------------------------------------------------------------------------------------------------- | ----- | ---------------------------------------- |
| 0    | 基础能力（闭源 LLM dispatch、项目脚手架）                                                                                           | ✅ 已交付 | —                                        |
| 1a   | Postgres + pgvector schema + NVIDIA embedding provider                                                                | ✅ 已交付 | schema migration 幂等；`embed()` 返回 768d 向量 |
| 1b   | 基于本地 fixture 的 dense retrieval + cited answer（pydantic）                                                               | ✅ 已交付 | 带有效 citations 的结构化 `Answer`              |
| 1c   | EDGAR ingestion + CLI driver                                                                                          | ✅ 已交付 | `finrag ingest` + `finrag ask` 端到端       |
| 1d   | NVIDIA NIM 作为 cloud open-weight provider                                                                              | ✅ 已交付 | `LLM_PROVIDER=nvidia` round-trip         |
| 1.5  | Mini-eval 跑在真实 AAPL FY2024 10-K 上（n=7,6 正例 + 1 insufficient）+ prompt `v1.1`（insufficient-context 用 JSON 返回） | ✅ 已交付 | hit@5 / recall@5 / MRR / nDCG@5 / 结构性 citation validity / LLM-judge faithfulness,数字见 [`eval/reports/wave1_5_mini_eval.md`](eval/reports/wave1_5_mini_eval.md) |
| 2    | Eval harness（30–50 条 curated items）                                                                                   | ⏳     | recall@k、MRR、nDCG、faithfulness           |
| 3    | Retrieval quality（chunking / table-aware / hybrid / rerank / query rewrite）                                           | ⏳     | recall@10 ablation table                 |
| 4    | ReAct agent + tools，然后迁移到 LangGraph                                                                                   | ⏳     | task success rate                        |
| 5A   | Public demo（FastAPI + Streamlit deployed）                                                                             | ⏳     | demo URL、citation UI                     |
| 5B   | Observability、cost、streaming、caching                                                                                  | ⏳     | p50 latency、$/query（before/after）        |
| 6    | Security & protocols（prompt-injection red team、output guardrails、MCP server）                                          | ⏳     | attack-success-rate 下降                   |
| 7    | Extensions & framework comparisons（LlamaIndex / DSPy / CrewAI / Cloudflare edge / CN A-share / memory / self-correct） | ⏳     | 每项对应 resume bullet                       |

## 技术栈（只使用云 API，不依赖本地服务）

| Layer | Primary | Backup(s) |
|---|---|---|
| LLM（闭源） | Google Gemini（`2.5-flash` / `-pro` / `-flash-lite`） | Anthropic Claude、OpenAI |
| LLM（cloud open-weight） | NVIDIA NIM / build.nvidia.com（Llama / Qwen / DeepSeek / Nemotron）— *planned, Wave 1d* | Together、Groq |
| Embedding | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5`（768d target） | Gemini `gemini-embedding-001`、Voyage、Cohere |
| Reranker | NVIDIA NeMo Retriever `nvidia/nv-rerankqa-mistral-4b-v3` | Jina `rerank-v2-multilingual`、Cohere |
| Vector + lexical store | **Neon Postgres + pgvector + tsvector FTS** | Supabase、Aiven |
| Agent | hand-written ReAct → LangGraph（Wave 4） | LlamaIndex（Wave 7 comparison） |
| Eval | hand-written + ragas；Wave 1d 后使用 NVIDIA NIM judge | Gemini judge fallback |
| Tracing | Langfuse Cloud | — |
| Output validation | pydantic | — |
| Guardrails（Wave 6） | NVIDIA NemoGuard + custom regex/PII | OpenAI Moderation |
| MCP（Wave 6） | official `mcp` Python SDK as server | — |
| API / UI | FastAPI + Streamlit | — |
| Deployment | Render / Railway / Fly.io free tier；Cloudflare Worker for edge demo | — |

Provider 切换由环境变量控制：`LLM_PROVIDER`、`EMBEDDING_PROVIDER`、`RERANKER_PROVIDER`。
Provider dispatch 使用单文件 `if/elif` 组织。

## 快速开始

```bash
uv sync --group dev
cp .env.example .env
# Wave 0 至少填写 GEMINI_API_KEY
uv run pytest
```

## 目录结构

```text
src/
  cli.py             # finrag ask / ingest 入口
  config.py          # 基于环境变量的 provider / model 配置
  llm.py             # LLM provider 分发（Gemini / Anthropic / OpenAI / NVIDIA）
  embed.py           # NVIDIA NeMo Retriever embedding 封装
  rerank.py          # reranker 分发
  db.py              # Postgres 连接 + schema 引导
  ingest.py          # parse -> split -> embed -> upsert
  retrieve.py        # vector / FTS / hybrid / rerank 检索
  rag.py             # retrieve -> prompt -> Answer (pydantic)
  agent.py           # ReAct 循环
  api.py             # FastAPI
  ui.py              # Streamlit
  guardrails.py      # 输入 / 输出过滤
  mcp_server.py      # 将工具暴露为 MCP server
  clients/           # 各 provider 的轻量 HTTP 客户端
    _http.py
    anthropic.py
    gemini.py
    openai.py
    nvidia.py
    edgar.py
  financial/         # EDGAR 抓取 + pydantic schema
    edgar.py
    schemas.py
  tools/             # agent 使用的金融工具
prompts/             # 版本化 prompt 文件
sql/                 # schema 迁移
data/                # raw / processed / fixtures
eval/                # 评测问题集、红队集、指标、报告
experiments/         # 消融脚本
tests/               # pytest 用例
edge/                # Cloudflare Worker 源码
.env.example
pyproject.toml
execution.md
README.md
README.zh-CN.md
```

## License

个人学习 / 作品集项目；不是生产软件。
