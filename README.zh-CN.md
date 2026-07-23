# FinRAG

[English](README.md) | [简体中文](README.zh-CN.md)

<p align="center">
  <a href="https://finrag-frontend.vercel.app/">
    <img alt="Live Demo" src="docs/live-demo-badge.svg">
  </a>
</p>

<p align="center">
  <a href="https://finrag-frontend.vercel.app/">
    <img alt="finrag —— RAG 模式对 Apple 10-K 提问，给出带 citation 的答案" src="docs/rag.png" width="820">
  </a>
</p>

> ### 🔗 在线体验 → **[finrag-frontend.vercel.app](https://finrag-frontend.vercel.app/)**
> 对 Apple 10-K 提问,直接在浏览器里看到**带 citation、可追溯**的答案——无需任何安装。

## 概览

**FinRAG 是一个面向 SEC EDGAR 披露文件（10-K、10-Q、8-K、20-F、DEF 14A）的、贴近生产形态的
检索增强生成（RAG）+ Agent 系统**,用**可追溯、带 citation 的答案**回答关于美股上市公司的投研问题。
这是一个动手型 LLM 应用工程项目,从一个基于云 API 的简单 RAG baseline,逐步演进成一个经过评测、
可观测、具备 agent 能力的产品:检索实验、金融工具、公开 demo,以及 Model Context Protocol（MCP）集成。

项目亮点:

- **Eval 驱动,而非凭感觉** —— 每一次 检索 / prompt / ranker 改动都由可复现的评测 harness 验证
  （recall@k · MRR · nDCG · faithfulness · answer-relevancy,用 LLM judge）,指标 delta 提交进 git。
- **混合检索 + 重排** —— pgvector 稠密检索与 Postgres tsvector BM25 用 RRF 融合,再叠加 NVIDIA NeMo
  重排;Wave 3 消融中 recall@10 **0.72 → 0.885**。
- **带引用的结构化答案** —— pydantic 校验答案结构，citation ID 必须指向本次检索到的
  filing chunk；未知 chunk ID 会让整条答案被拒绝。每条 quote 还会与 chunk 原文核对，
  不匹配时返回 `verified: false`，UI 会明确标记为**未验证**，而不是静默信任。
- **手写 ReAct agent + 5 个工具** —— 从零实现的 Thought → Action → Observation 循环（无框架）,
  覆盖 filing 检索、SEC XBRL 指标查询、跨公司对比、web search、计算器,并有 LangGraph A/B。
- **MCP server（stdio + 远程 HTTP）** —— 用 Model Context Protocol 暴露 finrag 工具；既能本地 stdio 运行，
  也能作为对反向代理友好的网络服务。设置 `MCP_TOKEN` 后 HTTP transport 才启用 bearer
  鉴权，任何公网暴露都必须设置该变量。
- **安全 guardrails + prompt 注入红队** —— 输入 / 上下文 / 输出 三层过滤（直接与间接注入、越狱、
  系统提示提取、PII、跨语言攻击）,由可复现的 attack-success-rate harness 度量:**ASR 0.29 → 0.07**。
- **可观测性与成本** —— fail-open 的 Langfuse tracing,每条回答都带每请求 token 用量与 `$/query` 估算。
- **前后端分离 Web 栈** —— Next.js 前端在服务端代理 FastAPI 请求（包括原样转发 SSE），
  API token 不会进入浏览器；UI 默认英文并支持切换中文，两个服务都按独立 Vercel Project 组织。

目标读者是开发者、分析师:从这个仓库里可以看到系统如何 ingest filing、检索证据、
校验结构化回答、度量质量,并通过 CLI、API、UI、agent tool 与 MCP 暴露完整工作流。

## Eval 驱动的结果 —— Wave 2 → Wave 3

本项目里每一次检索改动都由 eval harness 验证，而不是凭直觉。Wave 2 冻结了 baseline；
Wave 3 只改了检索管线，在 *同一套* 题目上重跑:

**评测配置** —— 两列除检索方式外完全一致:

| 配置项 | 取值 |
| --- | --- |
| 分块 | `fixed` |
| 题目数 | 38 |
| 生成模型 | `meta/llama-3.3-70b-instruct` |
| judge | `nvidia/llama-3.3-nemotron-super-49b-v1` |
| temperature | 0 |
| 检索方式 *(唯一变量)* | Wave 2 = dense · Wave 3 = hybrid RRF + cross-encoder 重排 |

| 指标 | Wave 2（dense baseline） | Wave 3（hybrid + rerank） | Δ |
| --- | --- | --- | --- |
| recall@5 | 0.66 | **0.87** | +0.21 |
| recall@10 | 0.80 | **0.97** | +0.17 |
| MRR | 0.64 | **0.80** | +0.16 |
| nDCG@10 | 0.65 | **0.84** | +0.19 |
| citation validity（结构性） | 0.82 | **0.97** | +0.15 |
| faithfulness † | 0.84 | **0.97** | +0.13 |
| answer relevancy † | 0.94 | **1.00** | +0.06 |
| correctness † | 0.84 | **0.97** | +0.13 |

检索指标（recall / MRR / nDCG）与 LLM 无关，提升完全归因于检索管线本身。† 生成类指标依赖
NVIDIA judge（Gemini 兜底），仅作方向性参考、非精确值。这些指标到此即达到平台期：
Wave 4+ 优化的是 *不同的* 维度（agent 任务成功率、延迟 / 每次查询成本、attack-success-rate），
而非单轮检索质量。Baseline：[`backend/eval/reports/wave_2.md`](backend/eval/reports/wave_2.md)；
最终配置：[`backend/eval/reports/wave_3_runeval.md`](backend/eval/reports/wave_3_runeval.md)；
逐步 ablation：[`backend/eval/reports/wave_3{a..f}.md`](backend/eval/reports/)。

## 路线图

| Wave | 标题                                                                                                                    | 状态    | 核心指标                                     |
| ---- | --------------------------------------------------------------------------------------------------------------------- | ----- | ---------------------------------------- |
| 0    | 基础能力（闭源 LLM dispatch、项目脚手架）                                                                                           | ✅ 已交付 | —                                        |
| 1a   | Postgres + pgvector schema + NVIDIA embedding provider                                                                | ✅ 已交付 | schema migration 幂等；`embed()` 返回 1024d 向量 |
| 1b   | 基于本地 fixture 的 dense retrieval + cited answer（pydantic）                                                               | ✅ 已交付 | 带有效 citations 的结构化 `Answer`              |
| 1c   | EDGAR ingestion + CLI driver                                                                                          | ✅ 已交付 | `finrag ingest` + `finrag ask` 端到端       |
| 1d   | NVIDIA NIM 作为 cloud open-weight provider                                                                              | ✅ 已交付 | `LLM_PROVIDER=nvidia` round-trip         |
| 1.5  | Mini-eval 跑在真实 AAPL FY2024 10-K 上（n=7,6 正例 + 1 insufficient）+ prompt `v1.1`（insufficient-context 用 JSON 返回） | ✅ 已交付 | hit@5 / recall@5 / MRR / nDCG@5 / 结构性 citation validity / LLM-judge faithfulness,数字见 [`backend/eval/reports/wave1_5_mini_eval.md`](backend/eval/reports/wave1_5_mini_eval.md) |
| 2    | Eval harness（38 条 curated items × 5 类,NIM judge + Gemini 兜底）                                                       | ✅ 已交付 | recall@10 0.80 / MRR 0.64 / nDCG@10 0.65 / citation validity 0.82 / faithfulness 0.84 / correctness 0.84,详见 [`backend/eval/reports/wave_2.md`](backend/eval/reports/wave_2.md) |
| 3    | Retrieval quality（chunking / table-aware / hybrid / rerank / query rewrite）                                           | ✅ 已交付 | recall@10 0.72 → **0.885**（hybrid + rerank），见下方[消融表](#wave-3-检索消融) |
| 4    | 手写 ReAct agent + 5 个工具，然后用 LangGraph 重写                                                                              | ✅ 已交付 | task success **0.94**（17/18）· tool-call accuracy 1.00 · 平均 3.0 步 —— [`backend/eval/reports/wave_4.md`](backend/eval/reports/wave_4.md)，A/B 见 [`wave_4_langgraph_compare.md`](backend/eval/reports/wave_4_langgraph_compare.md) |
| 5A   | Public demo（FastAPI + Streamlit）                                                                                      | ✅ 已交付 | 4 条路由经 HTTP 跑通；SSE 答案 + citation UI；p50 ≈ 12.6s —— [`backend/eval/reports/wave_5a.md`](backend/eval/reports/wave_5a.md) |
| 5B   | Observability、cost、caching                                                                                            | ✅ 已交付 | Langfuse spans（fail-open）· 每请求 token + `$/query`（NVIDIA 免费档 $0）—— [`backend/eval/reports/wave_5b.md`](backend/eval/reports/wave_5b.md) |
| 6    | Security & protocols（prompt-injection red team、output guardrails、MCP server）                                          | ✅ 已交付 | attack-success-rate **0.29 → 0.07**（间接注入 0.67 → 0.00）；finrag 作为 MCP server 暴露 —— [`backend/eval/reports/wave_6.md`](backend/eval/reports/wave_6.md) |

### Wave 3 检索消融

每一步都是在 38 条 eval 上的 A/B(检索指标与 LLM 无关,直接从 `retrieve()` 输出度量)。完整方法与分类表见 `backend/eval/reports/wave_3{a..f}.md`,每个 `backend/experiments/wave3_*.py` 可复现对应行。

| 步骤 | 改动 | 结果(对各自 baseline) | 是否上线 |
| ---- | ---- | --------------------- | -------- |
| 3a | 分块:fixed vs sentence-window vs parent-doc | recall@10 **fixed 0.722** > parent_doc 0.515 > sentence_window 0.247 | fixed(语义切分会切碎表格) |
| 3b | table-aware 入库(Docling) | numeric+table recall@10 0.738→0.671,**MRR +0.042** | 否 —— SEC HTML 抽取有损,混合结果 |
| 3c | hybrid pgvector + tsvector RRF | recall@10 0.722→**0.753**(+0.031),MRR +0.038 | ✅ `RETRIEVAL_MODE=hybrid` |
| 3d | cross-encoder 重排(top-50→10) | recall@10 0.753→**0.885**,MRR 0.681→0.801,nDCG→0.798 | ✅ `RERANK_ENABLED=1`(最大增益) |
| 3e | query rewriting(欠定查询) | HyDE recall@10 0.622→**0.676**(+0.054);multi-query −0.017 | 可配 `QUERY_REWRITE=multi_query\|hyde`;默认 `none` |
| 3f | embedding:NVIDIA vs Gemini | Gemini recall@10 0.722→**0.788**(+0.066),MRR +0.190 —— 但 3× 维度/成本 | 否 —— 保留与索引匹配的 1024d NVIDIA |

**上线默认:fixed 分块 + hybrid RRF + 重排** → recall@10 **0.722 → 0.885**,MRR **0.643 → 0.801**,nDCG@10 **0.610 → 0.798**(dense baseline → 最终配置;reranker 用 `nvidia/rerank-qa-mistral-4b`,即账号上实际可用、替代计划里 `-v3` 的变体)。

**为什么 `QUERY_REWRITE` 默认 `none`(3e):** 相对原始基线,HyDE 是用 top 排序精度(MRR −0.038 / nDCG −0.035 / recall@5 −0.047)换召回覆盖(recall@10 +0.054 / hit@5 +0.083 / hit@10 +0.055),multi-query 基本持平——都不是干净的提升。而且上线路径保留了 ticker/period 元数据过滤,本就已消解 rewriting 想解决的模糊查询,且每次改写都要多调一次 LLM。所以默认关、但保留为按次开关。完整逐指标对比与"欠定查询"测试设定见:[`backend/eval/reports/wave_3e.md`](backend/eval/reports/wave_3e.md)。

## Wave 4 —— ReAct agent + 工具

一个手写的 ReAct 循环（[`backend/src/agent.py`](backend/src/agent.py)）—— Thought → Action →
Observation，不依赖任何 agent 框架 —— 调度五个工具:

| 工具 | 来源 | 用途 |
| ---- | ---- | --- |
| `retrieve_filing` | Wave 3 的 hybrid + rerank 检索器 | 已入库 filing 里的叙事 / 定性事实 |
| `lookup_metric` | SEC XBRL `companyconcept` API | 单个审计过的年度数值（不走 RAG） |
| `compare_companies` | SEC XBRL | 多家公司同一指标并排对比（省略 `year` 时取最近的**共同**财年） |
| `calculator` | AST 求值（不用 `eval`） | 比率、百分比变化、求和 |
| `web_search` | Tavily（可选） | 语料库之外的事实 |

刻意的分工:**数值问题走结构化 XBRL,不走切碎的 prose**。每次未被输入护栏提前拦截的
本地 `Agent.run()` 都会把可回放的 JSONL trace 写到 `runs/<id>.jsonl`。复用同一个
`Agent` 实例时可以保留最近 N 轮 Q/A；公网 API 每个请求都通过 `run_agent()` 创建新实例，
因此不会跨 API 请求保留 memory。
在 18 题多步任务套件([`backend/eval/agent_questions.jsonl`](backend/eval/agent_questions.jsonl))上:

| 指标 | 结果 |
| ---- | ---- |
| task success（LLM-judge 正确性） | **0.94**（17/18;唯一一次 miss 是 ground-truth 数字过期,不是 agent 出错） |
| tool-call accuracy | **1.00** |
| 平均步数 / 任务 | **3.0**（目标 ≤ 6） |

同一个循环又用 LangGraph 重写了一遍([`backend/src/agent_lg.py`](backend/src/agent_lg.py)),即一个两节点的
`StateGraph`;两者产生相同的工具序列 —— A/B 见
[`backend/eval/reports/wave_4_langgraph_compare.md`](backend/eval/reports/wave_4_langgraph_compare.md)。
运行方式:`uv --directory backend run python -m src.agent "..."` 或 `uv --directory backend run python eval/run_eval.py --suite agent`。

> **设计取舍 —— 为什么用文本式 ReAct 而非 native tool-calling:** 本 wave 刻意手写文本式
> 循环(终止信号是模型输出 `Final Answer:`,而非 API 的 `tool_calls` 字段),目的是让循环、
> 停止条件、解析、容错都摆在明面上。代价是依赖模型可靠遵守格式(已用单参数兜底 / lookahead /
> `\nObservation:` 截断做容错);好处是**只要"文本进文本出"就行,换 provider 零改代码**
> —— 已实测同一份 agent 在 NVIDIA 与 Gemini 上均跑通。native tool-calling 由 API 保证结构化、
> 生产更稳但与 provider 绑定；当前代码没有实现 native function-calling。

## 技术栈（模型与数据使用托管服务，无需本地模型运行时）

| Layer | Primary | Options |
|---|---|---|
| LLM — 生成 | **NVIDIA NIM** `meta/llama-3.3-70b-instruct`（开源权重） | Gemini、Anthropic Claude、OpenAI |
| LLM — judge（eval） | **NVIDIA NIM** `nvidia/llama-3.3-nemotron-super-49b-v1`（推理微调，≥ 生成模型） | Gemini |
| Embedding | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5`（1024d） | Gemini `gemini-embedding-001` |
| Reranker | NVIDIA NeMo Retriever `nvidia/rerank-qa-mistral-4b` | — |
| Vector + lexical store | **Neon Postgres + pgvector + tsvector FTS** | — |
| Agent | hand-written ReAct + LangGraph 重写（Wave 4） | — |
| Eval | 手写指标（recall@k / MRR / nDCG + LLM judge） | — |
| Tracing | Langfuse Cloud | — |
| Output validation | pydantic + citation ID / quote 完整性校验 | — |
| Guardrails（Wave 6） | 确定性注入 / PII / 输出过滤 + 可选 NVIDIA NemoGuard content-safety | — |
| MCP（Wave 6） | official `mcp` Python SDK —— stdio + streamable HTTP server | — |
| API / UI | FastAPI（SSE + JSON）+ Next.js 16 / React 19 | Streamlit（旧版 VPS UI） |
| 异步入库 | Neon 持久化任务状态 + Upstash QStash 投递 | CLI 同步入库 |
| Deployment | 两个 Vercel Project（`backend` + `frontend`） | VPS 上使用 Docker Compose |

Provider 切换由环境变量控制：`LLM_PROVIDER`、`LLM_JUDGE_PROVIDER`、`EMBEDDING_PROVIDER`、
`RERANKER_PROVIDER`,使用单文件 `if/elif` dispatch。生成与 judge 的主用 provider 都是 NVIDIA NIM,
Gemini / Anthropic / OpenAI 仅作可选项。judge 使用比生成模型更强的模型
(`nemotron-super-49b` 推理微调,≥ `llama-3.3-70b` 生成模型)并在 temperature=0 下运行以保证评审可信。
模型选择是 eval 驱动的:`llama-4-maverick` 作生成被淘汰(在难数值题上过度推理、破坏严格 JSON 答案契约);
`deepseek-v4-pro` 虽更强但免费额度 429 限流过紧,无法支撑整轮 eval。

## 快速开始

### 环境要求

- Python 3.11 或 3.12，以及 [`uv`](https://docs.astral.sh/uv/)
- Node.js 20.19 或更高版本，以及 npm
- 支持 pgvector 的 PostgreSQL（生产环境使用 Neon）
- 用于 SEC EDGAR 的真实联系邮箱，以及 NVIDIA API key

### 后端与 CLI

```bash
git clone https://github.com/RealSerendipity/FinRAG.git
cd FinRAG

cp backend/.env.example .env
# 至少填写 EDGAR_USER_AGENT、DATABASE_URL 和 NVIDIA_API_KEY。
# 模板已经默认使用 NVIDIA 完成生成、embedding 和 rerank。

uv --directory backend sync --group dev
uv --directory backend run pytest

# 第一条业务命令会自动初始化数据库 schema。
uv --directory backend run finrag ingest --tickers AAPL --year 2024
uv --directory backend run finrag ask --ticker AAPL --year 2024 "What was Apple's R&D expense?"
```

Gemini、Anthropic、OpenAI、Langfuse、Tavily 和 NemoGuard 都是可选项。
只有使用旧版 Streamlit UI 或可选的 Docling 实验时才需要安装 `full` extra：

```bash
uv --directory backend sync --extra full --group dev
```

### 本地 FastAPI + Next.js

先在根目录 `.env` 中设置非空的 `API_TOKEN`，再复制前端模板，并让
`FINRAG_API_TOKEN` 使用相同的值：

```bash
cp frontend/.env.example frontend/.env.local
# frontend/.env.local：
# FINRAG_API_URL=http://127.0.0.1:8000
# FINRAG_API_TOKEN=<与 .env 中 API_TOKEN 相同的值>
npm --prefix frontend ci
```

从仓库根目录分别启动两个服务：

```bash
# 终端 1：FastAPI
uv --directory backend run uvicorn src.api:app --host 0.0.0.0 --port 8000

# 终端 2：Next.js
npm --prefix frontend run dev  # 打开 http://localhost:3000
```

Next.js UI 带一个 **RAG / Agent 模式开关**（单轮带引用答案 vs 多步调用工具的 agent）
以及一个持久化的**入库面板**。所有浏览器请求都由 Next.js Route Handler 代理到
FastAPI，凭据只保留在服务端。

以上配置可以直接使用本地 RAG 和 Agent。网页入库面板会通过 QStash 发布后台任务，
所以还需要 `QSTASH_TOKEN`、两把 QStash 签名密钥，以及公网可访问的
`FINRAG_PUBLIC_API_URL`。纯本地环境请使用 CLI 入库。

| Agent 模式 —— 运行中 | Agent 模式 —— 多步工具调用轨迹 |
| :---: | :---: |
| ![finrag agent running](docs/agent-running.png) | ![finrag agent result](docs/agent-result.png) |

*Agent 模式回答多步问题（"Apple 的 R&D / 营收比从 FY2023 到 FY2024 如何变化？"）：
ReAct 循环对两个年度分别调 `lookup_metric`（SEC XBRL）取 R&D 和营收，再调
`calculator`，并展示完整的推理轨迹。*

从仓库根目录执行当前完整检查：

```bash
uv --directory backend run pytest
npm --prefix frontend run test:run
npm --prefix frontend run lint
npm --prefix frontend run build
```

### 生产部署

| 服务 | 公网地址 |
| --- | --- |
| Next.js 前端 | [https://finrag-frontend.vercel.app](https://finrag-frontend.vercel.app/) |
| FastAPI 后端 | [https://fin-rag-nu.vercel.app](https://fin-rag-nu.vercel.app/) |
| 后端健康检查 | [https://fin-rag-nu.vercel.app/health](https://fin-rag-nu.vercel.app/health) |

同一个 GitHub 仓库需要在 Vercel 中导入两次：

| Vercel Project | Root Directory | 配置 |
| --- | --- | --- |
| `fin-rag` | `backend` | FastAPI 入口位于 `backend/pyproject.toml`；函数配置位于 `backend/vercel.json` |
| `finrag-frontend` | `frontend` | Vercel 自动识别 Next.js |

前端 Production 环境变量：

```dotenv
FINRAG_API_URL=https://fin-rag-nu.vercel.app
FINRAG_API_TOKEN=<与后端 API_TOKEN 相同的值>
```

后端需要按 `backend/.env.example` 配置所选 provider、Neon 和鉴权变量。网页异步入库
还要设置 `FINRAG_PUBLIC_API_URL=https://fin-rag-nu.vercel.app` 并连接 Upstash
QStash；该集成会自动注入 `QSTASH_URL`、`QSTASH_TOKEN`、
`QSTASH_CURRENT_SIGNING_KEY` 和 `QSTASH_NEXT_SIGNING_KEY`。修改环境变量后需要重新部署
对应服务。

### Docker / VPS

旧版 Streamlit UI 仍保留给单容器 VPS 部署。镜像读取根目录 `.env`，在容器内部
8000 端口运行 FastAPI，只向宿主机暴露 Streamlit 的 8501 端口：

```bash
docker compose -f infra/compose.yaml up --build
# 打开 http://localhost:8501
```

公网 VPS 使用时，请在 8501 端口前配置自己的 TLS 反向代理。与本地网页入库面板相同，
异步入库需要 QStash 和公网 callback URL；CLI 入库不需要。

### 直接调用 API

```bash
curl http://127.0.0.1:8000/health
curl -N -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer replace-with-your-api-token' \
  -d '{"question":"What was Apple total net sales in fiscal 2024?","ticker":"AAPL","year":2024}'
```

路由包括：`GET /health`、`POST /ask`（SSE：status → answer → done，带心跳）、
`POST /agent`（ReAct，JSON）、`POST /ingest`（返回 **202 + job_id**），以及
`GET /ingest/{job_id}`（轮询状态/结果）。每个 `/ask` 和 `/agent` 响应都包含延迟、
token 用量、按实际模型计算的 `$/query` 估算；配置 `LANGFUSE_*` 后还会返回
fail-open 的 `trace_url`。意外失败返回稳定的 `internal_error`，异常细节只保留在服务端日志。

**鉴权。** 设置 `API_TOKEN` 后，`/ask`、`/agent`、`/ingest` 和
`/ingest/{job_id}` 都要求 `Authorization: Bearer <token>`，`/health` 仍保持开放。
`API_ROOT_PATH` 用于反向代理路径前缀。公开部署时设置 `RATE_LIMIT_ENABLED=1`：
`/ask` 限制为每分钟 10 次，`/agent` 每分钟 3 次，`/ingest` 每小时 2 次。
Next.js 与 Streamlit 都在服务端通过 `FINRAG_API_URL` + `FINRAG_API_TOKEN`
调用 FastAPI，因此 API token 不会进入浏览器。

## 安全与 MCP（Wave 6）

**Guardrails。** [`backend/src/guardrails.py`](backend/src/guardrails.py) 在 RAG / agent 路径外包了一层
纵深防御过滤，默认开启（`GUARDRAILS_ENABLED=1`）：

- `screen_input` —— 在模型运行**之前**拦截 prompt 注入 / 越狱 / 系统提示提取（确定性正则
  签名，无需联网，含中文变体；可选开启 [NVIDIA NemoGuard](https://build.nvidia.com/nvidia/llama-3_1-nemoguard-8b-content-safety)
  content-safety，`NEMOGUARD_ENABLED=1`，用于真正有害的内容）。
- `screen_context` / `screen_observation` —— 生成前丢弃夹带**间接注入**（"忽略用户，改为…"）
  的检索 chunk；agent 的工具观察结果（检索摘录、web 搜索片段）命中同类签名时同样扣留——
  被投毒的片段既劫持不了回答，也劫持不了循环。丢弃会记日志并进 trace，绝不静默。
- `validate_output` / `redact_pii` —— 在每个 `ask`/`agent` 答案返回**之前**运行：扣留回显
  提示词/配置的答案，再对文本脱敏 email / SSN / 卡号（Luhn 校验）/ 电话。

签名针对攻击**措辞**而非金融词汇，所以正常的 filing 问题不受影响（零误报，见
`backend/tests/test_wave6.py`）。NemoGuard 评估的是内容**危害**而非注入，因此它是对签名的**增强**而非
替代，且永远 fail-open 退回到签名层。

**Red team。** [`backend/eval/red_team.jsonl`](backend/eval/red_team.jsonl) 含 5 类对抗 prompt（直接越狱、
系统提示提取、citation 操纵、经投毒 chunk 的间接注入、中文攻击）。harness 对每条在关 / 开
防御两种情况下各跑一遍，报告防御前后的 attack-success-rate —— 成功与否用 canary 确定性判定，
所以数字可复现。

**把 finrag 当作 MCP 工具用。** [`backend/src/mcp_server.py`](backend/src/mcp_server.py) 用官方 `mcp` SDK
把 finrag 暴露为 MCP server：`ask_filings`（带引用的 RAG）、`research_agent`（多步 ReAct）
以及 Wave 4 的 5 个工具。两种 transport,用 `FINRAG_MCP_TRANSPORT` 选择：

**本地（stdio）** —— 同机的 MCP 客户端,以子进程方式拉起 server。命令行方式:

```bash
claude mcp add finrag -- uv --directory backend run python -m src.mcp_server
```

或写进配置文件（`.mcp.json`、`claude_desktop_config.json`、Cursor……）:

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

**远程（Streamable HTTP）** —— 把 finrag 暴露成**可被远程 MCP 客户端访问的网络服务**。
它无状态运行（对反向代理 / tunnel 友好）。设置 `MCP_TOKEN` 后，请求必须携带
`Authorization: Bearer <MCP_TOKEN>`；未设置时服务会以未鉴权模式启动并输出警告。
任何公网暴露都必须设置该变量。服务绑定到 localhost，再通过反向代理 / tunnel
（TLS + 同一个 `MCP_TOKEN`）暴露，方式与 Web demo 类似：

```bash
MCP_TOKEN=your-secret FINRAG_MCP_TRANSPORT=http uv --directory backend run python -m src.mcp_server
# → 在 http://127.0.0.1:8200/mcp 提供 Streamable HTTP 服务
```

然后让任意支持 HTTP 的 MCP 客户端用 bearer 头连接公网 `/mcp` URL。命令行方式:

```bash
claude mcp add --transport http finrag https://your-domain/mcp \
  --header "Authorization: Bearer your-secret"
```

或写进配置文件（`.mcp.json`、Cursor、VS Code……）:

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

同一套护栏覆盖整个 MCP 面：`ask_filings` / `research_agent` 从 RAG/agent 路径继承防御；
直接暴露的 Wave 4 工具会先筛查字符串入参，再像 agent observation 一样筛查输出
（投毒的摘录会被扣留，而不是返回给客户端）。对外暴露时请把
`FINRAG_MCP_ALLOWED_HOSTS`（host 白名单）和 `MCP_TOKEN`（bearer 鉴权）一起设置——
在代理 TLS 之上再加一层纵深防御。

### 实际使用验收

```bash
# 1) 红队：跑出 ASR before/after，落到 backend/eval/reports/wave_6.md（+ 时间戳原始 run）
LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= uv --directory backend run python -u eval/run_red_team.py
#    → SUMMARY {"asr_before": ~0.29, "asr_after": ~0.07}

# 2) MCP server：用官方 inspector 验证 tools/list（需要 npx）
npx @modelcontextprotocol/inspector --cli uv --directory backend run python -m src.mcp_server --method tools/list
#    → 打印含 7 个工具的 JSON（ask_filings、research_agent + Wave 4 的 5 个工具）
#    去掉 --cli/--method 则启动浏览器 UI，可交互调用工具

# 3) 用上面的配置把 server 接入任意 MCP 客户端,问 "What was AAPL revenue in FY2024?"
#    → 经 finrag 的 ask_filings 返回带 citation 的答案

# 4) 防御对普通问题零误报 + 拦截攻击（离线,无需 key）
uv --directory backend run python -m pytest tests/test_wave6.py -q     # guardrails + MCP 测试全过
```

防御默认开启,所以 `finrag ask` / `/agent` / MCP 在实际使用中已被保护：对注入 prompt 直接返回
固定拒答（`GUARDRAILS_ENABLED=0` 可关闭以测无防御 baseline）。

## 分块策略(可配置）

分块策略在 ingest 时可配：用 `--chunk-strategy` 或环境变量 `CHUNK_STRATEGY` 选择(默认 `fixed`)。
它只影响 filing 在 embedding 前如何切分,检索与回答逻辑不变。非法值会**立即报错**(在任何 EDGAR 抓取 / embedding 之前)。

```bash
# 方式一:用 CLI flag 按次指定
uv --directory backend run finrag ingest --tickers AAPL --year 2024 --chunk-strategy section

# 方式二:在 .env 里设默认值(CHUNK_STRATEGY=section)后正常运行
uv --directory backend run finrag ingest --tickers AAPL --year 2024
```

| 策略 | 做什么 |
| --- | --- |
| `fixed`(默认) | 段落打包的 token 窗口(约 300 cl100k token;超长段落按重叠切分) |
| `sentence_window` | N 句的重叠窗口,保持句子完整 |
| `section` | 按 10-K 结构标题(Item / Part)切,并给每个 chunk 前缀所在节标题 |
| `parent_doc` | embedding 小 child 用于精确检索,大 parent 块存进 metadata;`ask()` 把 parent 作为上下文喂给 LLM |

在 AAPL 10-K 这套 eval 语料上 `fixed` 胜出 —— 语料小且数值/表格密集,更细的分块会抬高 recall 分母(见 [`backend/eval/reports/wave_3a.md`](backend/eval/reports/wave_3a.md) 与 [`wave_3g.md`](backend/eval/reports/wave_3g.md))。其余策略保留,因为最优策略取决于语料;换语料时切换并重新测量即可。

### 新增一种分块策略

策略名只有一个事实源(`backend/src/ingest.py` 的 `VALID_CHUNK_STRATEGIES`),所以新增是一处小的局部改动:

1. 在 `backend/src/ingest.py` 写一个 `chunk_<name>(text, ...) -> list[str]`（若需要 parent 上下文则 `-> list[tuple[str, str]]`）。
2. 把 `"<name>"` 加进 `VALID_CHUNK_STRATEGIES`，并在 `build_chunks()` 加一个分支，返回 `list[tuple[str, dict]]` —— 生成时要用的上下文（如 parent 块）放进 `metadata` dict。
3. 若用了 `metadata["parent_text"]`,生成端已经会优先使用(`rag._context_text`),无需再接。
4. `CHUNK_STRATEGY` 环境变量、`--chunk-strategy` flag、fail-fast 校验都会自动从 `VALID_CHUNK_STRATEGIES` 识别这个新名字。
5. 在 `backend/tests/test_wave3.py` 加单测,并用 `backend/experiments/wave3_*.py` 脚本对 `backend/eval/run_eval.py` 做 A/B。

## Monorepo 目录结构

```text
frontend/
  app/                # Next.js 页面与固定 /api 代理 Route Handler
  components/         # 中英文 RAG、Agent、健康状态与入库 UI
  lib/                # i18n、SSE 解析、类型与仅服务端可见的 FastAPI client
  package.json
  package-lock.json
backend/
  src/
    api.py            # FastAPI 路由与 SSE
    rag.py            # RAG 回答流程
    agent.py          # 手写 ReAct 循环
    ingest.py         # filing 入库管线
    ingest_jobs.py    # 持久化入库任务状态
    qstash_queue.py   # QStash 发布与签名校验
    clients/          # provider 客户端
    financial/        # SEC filing 与 XBRL 支持
    tools/            # Agent 工具
  prompts/           # 版本化 prompt 文件（answer_v*、react_v1）
  sql/               # 运行时 schema 迁移
  data/              # raw / processed / fixtures
  eval/              # 评测集、指标与报告
  experiments/       # 检索消融脚本
  tests/             # pytest 用例
  pyproject.toml
  uv.lock
  vercel.json        # 后端 Vercel Project 配置
infra/
  Dockerfile
  compose.yaml
  entrypoint.sh
docs/                # 文档资源
README.md            # 英文文档（保留在仓库根目录）
README.zh-CN.md      # 中文文档（保留在仓库根目录）
```

## License

[MIT](LICENSE)。这是个人学习 / 作品集项目，软件按现状提供，不附带任何保证。
