# FinRAG

[English](README.md) | [简体中文](README.zh-CN.md)

面向 SEC EDGAR 披露文件（10-K / 10-Q / 8-K / 20-F / DEF 14A）的检索增强与 Agent 系统。
这是一个动手型 LLM 应用工程项目，覆盖金融研究工作流、结构化回答、citation、eval 和可部署的 AI 产品形态。

## 概览

FinRAG 是一个作品集级别的金融 RAG 项目，用于在公司披露文件上回答投研问题，并提供可追溯 citation。
项目目标是从一个基于云 API 的简单 RAG baseline，逐步演进成具备 eval、observability、agent tools、公开 demo 和 MCP 集成的应用系统。

目标读者可以从这个仓库里看到：系统如何 ingest filing、检索证据、校验结构化回答、度量质量，并通过 CLI、API、UI 和 agent tool 暴露完整工作流。

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
而非单轮检索质量。Baseline：[`eval/reports/wave_2.md`](eval/reports/wave_2.md)；
最终配置：[`eval/reports/wave_3_runeval.md`](eval/reports/wave_3_runeval.md)；
逐步 ablation：[`eval/reports/wave_3{a..f}.md`](eval/reports/)。

## 路线图

| Wave | 标题                                                                                                                    | 状态    | 核心指标                                     |
| ---- | --------------------------------------------------------------------------------------------------------------------- | ----- | ---------------------------------------- |
| 0    | 基础能力（闭源 LLM dispatch、项目脚手架）                                                                                           | ✅ 已交付 | —                                        |
| 1a   | Postgres + pgvector schema + NVIDIA embedding provider                                                                | ✅ 已交付 | schema migration 幂等；`embed()` 返回 1024d 向量 |
| 1b   | 基于本地 fixture 的 dense retrieval + cited answer（pydantic）                                                               | ✅ 已交付 | 带有效 citations 的结构化 `Answer`              |
| 1c   | EDGAR ingestion + CLI driver                                                                                          | ✅ 已交付 | `finrag ingest` + `finrag ask` 端到端       |
| 1d   | NVIDIA NIM 作为 cloud open-weight provider                                                                              | ✅ 已交付 | `LLM_PROVIDER=nvidia` round-trip         |
| 1.5  | Mini-eval 跑在真实 AAPL FY2024 10-K 上（n=7,6 正例 + 1 insufficient）+ prompt `v1.1`（insufficient-context 用 JSON 返回） | ✅ 已交付 | hit@5 / recall@5 / MRR / nDCG@5 / 结构性 citation validity / LLM-judge faithfulness,数字见 [`eval/reports/wave1_5_mini_eval.md`](eval/reports/wave1_5_mini_eval.md) |
| 2    | Eval harness（38 条 curated items × 5 类,NIM judge + Gemini 兜底）                                                       | ✅ 已交付 | recall@10 0.80 / MRR 0.64 / nDCG@10 0.65 / citation validity 0.82 / faithfulness 0.84 / correctness 0.84,详见 [`eval/reports/wave_2.md`](eval/reports/wave_2.md) |
| 3    | Retrieval quality（chunking / table-aware / hybrid / rerank / query rewrite）                                           | ✅ 已交付 | recall@10 0.80 → **0.97**（hybrid + rerank），见上方 Eval 驱动结果表 |
| 4    | ReAct agent + tools，然后迁移到 LangGraph                                                                                   | ⏳     | task success rate                        |
| 5A   | Public demo（FastAPI + Streamlit deployed）                                                                             | ⏳     | demo URL、citation UI                     |
| 5B   | Observability、cost、streaming、caching                                                                                  | ⏳     | p50 latency、$/query（before/after）        |
| 6    | Security & protocols（prompt-injection red team、output guardrails、MCP server）                                          | ⏳     | attack-success-rate 下降                   |
| 7    | Extensions & framework comparisons（LlamaIndex / DSPy / CrewAI / Cloudflare edge / CN A-share / memory / self-correct） | ⏳     | 每项对应 resume bullet                       |

### Wave 3 检索消融

每一步都是在 38 条 eval 上的 A/B(检索指标与 LLM 无关,直接从 `retrieve()` 输出度量)。完整方法与分类表见 `eval/reports/wave_3{a..f}.md`,每个 `experiments/wave3_*.py` 可复现对应行。

| 步骤 | 改动 | 结果(对各自 baseline) | 是否上线 |
| ---- | ---- | --------------------- | -------- |
| 3a | 分块:fixed vs sentence-window vs parent-doc | recall@10 **fixed 0.722** > parent_doc 0.515 > sentence_window 0.247 | fixed(语义切分会切碎表格) |
| 3b | table-aware 入库(Docling) | numeric+table recall@10 0.738→0.671,**MRR +0.042** | 否 —— SEC HTML 抽取有损,混合结果 |
| 3c | hybrid pgvector + tsvector RRF | recall@10 0.722→**0.753**(+0.031),MRR +0.038 | ✅ `RETRIEVAL_MODE=hybrid` |
| 3d | cross-encoder 重排(top-50→10) | recall@10 0.753→**0.885**,MRR 0.681→0.801,nDCG→0.798 | ✅ `RERANK_ENABLED=1`(最大增益) |
| 3e | query rewriting(欠定查询) | HyDE recall@10 0.622→**0.676**(+0.054);multi-query −0.017 | 可配 `QUERY_REWRITE=multi_query\|hyde`;默认 `none` |
| 3f | embedding:NVIDIA vs Gemini | Gemini recall@10 0.722→**0.788**(+0.066),MRR +0.190 —— 但 3× 维度/成本 | 否 —— 保留与索引匹配的 1024d NVIDIA |

**上线默认:fixed 分块 + hybrid RRF + 重排** → recall@10 **0.722 → 0.885**,MRR **0.643 → 0.801**,nDCG@10 **0.610 → 0.798**(dense baseline → 最终配置;reranker 用 `nvidia/rerank-qa-mistral-4b`,即账号上实际可用、替代计划里 `-v3` 的变体)。

**为什么 `QUERY_REWRITE` 默认 `none`(3e):** 相对原始基线,HyDE 是用 top 排序精度(MRR −0.038 / nDCG −0.035 / recall@5 −0.047)换召回覆盖(recall@10 +0.054 / hit@5 +0.083 / hit@10 +0.055),multi-query 基本持平——都不是干净的提升。而且上线路径保留了 ticker/period 元数据过滤,本就已消解 rewriting 想解决的模糊查询,且每次改写都要多调一次 LLM。所以默认关、但保留为按次开关。完整逐指标对比与"欠定查询"测试设定见:[`eval/reports/wave_3e.md`](eval/reports/wave_3e.md)。

## 技术栈（只使用云 API，不依赖本地服务）

| Layer | Primary | Backup(s) |
|---|---|---|
| LLM — 生成 | **NVIDIA NIM** `meta/llama-3.3-70b-instruct`（免费开源权重） | Gemini、Anthropic Claude、OpenAI |
| LLM — judge（eval） | **NVIDIA NIM** `nvidia/llama-3.3-nemotron-super-49b-v1`（推理微调，≥ 生成模型） | Gemini 兜底 |
| Embedding | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5`（1024d） | Gemini `gemini-embedding-001`、Voyage、Cohere |
| Reranker | NVIDIA NeMo Retriever `nvidia/rerank-qa-mistral-4b`（账号上实际可用的变体） | Jina `rerank-v2-multilingual`、Cohere |
| Vector + lexical store | **Neon Postgres + pgvector + tsvector FTS** | Supabase、Aiven |
| Agent | hand-written ReAct → LangGraph（Wave 4） | LlamaIndex（Wave 7 comparison） |
| Eval | hand-written + ragas；Wave 1d 后使用 NVIDIA NIM judge | Gemini judge fallback |
| Tracing | Langfuse Cloud | — |
| Output validation | pydantic | — |
| Guardrails（Wave 6） | NVIDIA NemoGuard + custom regex/PII | OpenAI Moderation |
| MCP（Wave 6） | official `mcp` Python SDK as server | — |
| API / UI | FastAPI + Streamlit | — |
| Deployment | Render / Railway / Fly.io free tier；Cloudflare Worker for edge demo | — |

Provider 切换由环境变量控制：`LLM_PROVIDER`、`LLM_JUDGE_PROVIDER`、`EMBEDDING_PROVIDER`、
`RERANKER_PROVIDER`,使用单文件 `if/elif` dispatch。生成与 judge 的主用 provider 都是 NVIDIA NIM,
Gemini / Anthropic / OpenAI 仅作 backup。judge 使用比生成模型更强的模型
(`nemotron-super-49b` 推理微调,≥ `llama-3.3-70b` 生成模型)并在 temperature=0 下运行以保证评审可信。
模型选择是 eval 驱动的:`llama-4-maverick` 作生成被淘汰(在难数值题上过度推理、破坏严格 JSON 答案契约);
`deepseek-v4-pro` 虽更强但免费额度 429 限流过紧,无法支撑整轮 eval。

## 快速开始

```bash
uv sync --group dev
cp .env.example .env
# Wave 0 至少填写 GEMINI_API_KEY
uv run pytest
```

## 分块策略(可配置）

分块策略在 ingest 时可配：用 `--chunk-strategy` 或环境变量 `CHUNK_STRATEGY` 选择(默认 `fixed`)。
它只影响 filing 在 embedding 前如何切分,检索与回答逻辑不变。非法值会**立即报错**(在任何 EDGAR 抓取 / embedding 之前)。

```bash
# 方式一:用 CLI flag 按次指定
uv run finrag ingest --tickers AAPL --year 2024 --chunk-strategy section

# 方式二:在 .env 里设默认值(CHUNK_STRATEGY=section)后正常运行
uv run finrag ingest --tickers AAPL --year 2024
```

| 策略 | 做什么 |
| --- | --- |
| `fixed`(默认) | 段落打包的 token 窗口(约 300 cl100k token;超长段落按重叠切分) |
| `sentence_window` | N 句的重叠窗口,保持句子完整 |
| `section` | 按 10-K 结构标题(Item / Part)切,并给每个 chunk 前缀所在节标题 |
| `parent_doc` | embedding 小 child 用于精确检索,大 parent 块存进 metadata;`ask()` 把 parent 作为上下文喂给 LLM |

在 AAPL 10-K 这套 eval 语料上 `fixed` 胜出 —— 语料小且数值/表格密集,更细的分块会抬高 recall 分母(见 [`eval/reports/wave_3a.md`](eval/reports/wave_3a.md) 与 [`wave_3g.md`](eval/reports/wave_3g.md))。其余策略保留,因为最优策略取决于语料;换语料时切换并重新测量即可。

### 新增一种分块策略

策略名只有一个事实源(`src/ingest.py` 的 `VALID_CHUNK_STRATEGIES`),所以新增是一处小的局部改动:

1. 在 `src/ingest.py` 写一个 `chunk_<name>(text, ...) -> list[str]`(若需要 parent 上下文则 `-> list[(child, parent)]`)。
2. 把 `"<name>"` 加进 `VALID_CHUNK_STRATEGIES`,并在 `build_chunks()` 加一个分支,返回 `list[(content, metadata)]` —— 生成时要用的上下文(如 parent 块)放进 `metadata` dict。
3. 若用了 `metadata["parent_text"]`,生成端已经会优先使用(`rag._context_text`),无需再接。
4. `CHUNK_STRATEGY` 环境变量、`--chunk-strategy` flag、fail-fast 校验都会自动从 `VALID_CHUNK_STRATEGIES` 识别这个新名字。
5. 在 `tests/test_wave3.py` 加单测,并用 `experiments/wave3_*.py` 脚本对 `eval/run_eval.py` 做 A/B。

## 目录结构

```text
src/
  cli.py             # finrag ask / ingest 入口
  config.py          # 基于环境变量的 provider / model 配置
  llm.py             # LLM provider 分发（Gemini / Anthropic / OpenAI / NVIDIA）
  embed.py           # embedding 分发（NVIDIA 主用，Gemini 用于 Wave 3f）
  rerank.py          # reranker 分发（NVIDIA NeMo Retriever）
  db.py              # Postgres 连接 + schema 引导
  ingest.py          # parse -> chunk（fixed / sentence-window / section / parent-doc）-> embed -> upsert
  retrieve.py        # vector / FTS / hybrid (RRF) / rerank 检索
  query_rewrite.py   # normalize / multi-query / HyDE（Wave 3e）
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
  financial/         # EDGAR 抓取 + pydantic schema + 表格抽取
    edgar.py
    schemas.py
    table_extract.py # Docling 表格感知抽取（Wave 3b）
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
