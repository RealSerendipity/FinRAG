# finrag — 执行路线图

本文件是 finrag 项目的**唯一执行手册**:每个 wave 严格按照「学习先修 → 实现 → 验收」三段顺序排列,直接照着做即可。

公开里程碑表见 [README.md](README.md)。

---

## 1. 目标(按优先级)

1. **端到端覆盖 LLM application engineer 技能集** —— 数据、检索、agent、eval、生产化、安全、协议。
2. **作品集导向**:每个 wave 都交付一个可独立 demo 的能力切片,并产生一个可写进简历的指标变化。
3. **可商业化**:围绕真实用户问题(英文披露文件 → 多语言问答),使用 free-tier-only stack,demo 可云端部署。
4. **边学边做**:每个 sub-wave 是一个完整学习闭环 —— *读 → 提出假设 → 写代码 → 测量 → 写小结*。

---

## 2. 领域

美股上市公司披露文件上的金融 / 投研问答(10-K、10-Q、8-K、earnings transcripts)。
初始锚定 5–10 家公司 × 2–3 个财年。Wave 7 可扩展到 CN A 股年报作为商业化差异化方向。

---

## 3. 工程规则(开工前必读,执行中持续遵守)

这些规则用来防止重蹈上一次"提前抽象、文档泛滥"的覆辙。在没有出现具体反例之前不要妥协。

### 3.1 不提前抽象
- 不允许 `base/factory/providers/registry/discovery` 这类三件套。
- 多 provider 切换 = **单文件 `if/elif` 分发**。只有当某个分支真正长出 5 个以上 helper 或文件超过约 400 行时,才拆。
- **第二个具体实现出现时**才引入接口,从来不在第一个时引入。
- 领域代码扁平地放在 `src/financial/`。新领域用 *fork + 改 prompt* 处理,不走抽象。

### 3.2 Eval-driven
- 任何影响 retrieval / prompt / ranker / agent loop 的改动,都要跑 `eval/run_eval.py` 并把指标 diff 提交到 git。
- 影响指标的 commit message 必须带一行 delta,例如:`Wave 3c: hybrid retrieval — recall@10 0.62→0.74, MRR 0.41→0.51`。

### 3.3 扁平结构优先
- 一个 concern 一个文件。3 个以上模块围绕同一个清晰命名的概念协作时,才建子包。
- `src/` 按数据流组织:`ingest → retrieve → rag → agent → api/ui`。

### 3.4 文档不蔓延
- 允许的叙事文档:`README.md` 和 `execution.md`(本文件)。仅此两份。
- Wave 级写作产物全部归到 `eval/reports/wave_<id>.md`,以**证据**形式存在,而不是散文。
- 不要建 `NOTES.md` / `LEARNINGS.md` / `JOURNAL.md` / per-feature 设计文档。代码 + git log + eval 报告应足以重建意图。

### 3.5 代码体量
- Wave 5B 之前 `src/` 总行数 **不超过 3000 行**。超出即代表过度工程化,先做减法重构再继续。

### 3.6 注释
- 默认不写注释。仅当 *why* 不显然时才写一行(workaround、不变量、外部 API 约束)。**代码注释一律用英文。**

### 3.7 配置
- 运行时参数走 `.env` 环境变量。
- 默认值就近写在消费它的代码里,不集中塞进巨大的 config object。

### 3.8 测试
- 每个 wave 收尾时 `pytest` 必须通过。
- 依赖网络 / API key 的测试,在 key 缺失时必须 clean skip,不能因为没配环境就失败。

### 3.9 学习节奏(本项目特有)
- **3.9.1 先读再写**:开 sub-wave 之前,花最多半天读对应章节(见 §4 阅读地图)和最多 1 篇主参考。把"我要验证的假设"用 50–100 字写进该 wave 的首个 commit message。**说不出假设就别开始写代码。**
- **3.9.2 一个 sub-wave、一个 commit、一份小结**:小结里必须有 *做了什么尝试、数字怎么变、什么让你意外*。**没数字 + 没意外 = 不该进 repo**。
- **3.9.3 压住 Java 架构师本能**:十年后端的本能会推你提前写 `LLMProvider` 接口和策略模式。规则就是:**第二个具体实现触发抽象,而不是第一个。**
- **3.9.4 Wave 1.5 / Wave 2 不能跳**:eval 是唯一没有可见 feature 输出的 sub-wave,所以最容易在 deadline 压力下被跳过。**跳了之后,所有后续数字都失去意义。**
- **3.9.5 学习产物 ≠ 叙事文档**:学习笔记进 commit message 或 `eval/reports/`,不要建 `NOTES.md`。这违反 §3.4。

---

## 4. 与 mlabonne/llm-course "The LLM Engineer" 的对应表

每个 wave 开工前读对应章节,完工后在 `eval/reports/wave_<id>.md` 末尾加一段 "Theory ↔ Practice" 小结(50–150 字)。

| Wave | LLM Engineer 章节 | 阅读重点 |
|---|---|---|
| 0 | §1 Running LLMs | API 调用、token 用量、各家 SDK 差异 |
| 1a | §2 Building a Vector Storage | embedding、向量库、HNSW 参数、cosine vs L2 |
| 1b | §2 Vector Storage + §3 RAG basics | similarity search、citation 契约、structured output |
| 1c | §3 RAG ingestion | document loaders、splitters、metadata 设计 |
| 1d | §1 Running LLMs(open-weight 部分) | NIM / Together / Groq 路由对比 |
| 1.5 / 2 | §3 RAG eval | recall@k、MRR、nDCG、faithfulness、ragas、LLM-as-judge bias |
| 3 | §4 Advanced RAG | hybrid search、RRF、reranking、query rewriting、HyDE、parent-doc |
| 4 | §5 Agents | ReAct、tool-calling、LangGraph、agent eval |
| 5A | §7 Deploying LLMs | FastAPI、Streamlit、Render / Fly 部署、cold start |
| 5B | §6 Inference Optimization + §7 observability | prompt cache、KV cache 概念、Langfuse、$/query 计算 |
| 6 | §8 Securing LLMs | prompt injection 类型学、output guardrails、ASR 测量 |
| 7 | §5 Agents 深入 + §4 选定方向 | 按选中的 extension 精读对应资料 |

**一句话原则**:llm-course 是每个 wave 的"理论层",不另起平行项目;所有产出归到 finrag 仓库。

---

## 5. 技术栈(每层 primary + backup)

| Layer | Primary | Backup(s) |
|---|---|---|
| LLM(closed APIs) | Google Gemini(`2.5-flash` / `-pro` / `-flash-lite`) | Anthropic Claude、OpenAI |
| LLM(open-weight via cloud) | NVIDIA NIM / build.nvidia.com(Llama / Qwen / DeepSeek / Nemotron)—— *Wave 1d 启用* | Together AI、Groq |
| Embedding | NVIDIA NeMo Retriever `nvidia/nv-embedqa-e5-v5`(768d) | Gemini `gemini-embedding-001`、Voyage `voyage-3-large`、Cohere `embed-v4.0` |
| Reranker | NVIDIA NeMo Retriever `nvidia/nv-rerankqa-mistral-4b-v3` | Jina `rerank-v2-multilingual`、Cohere `rerank-v3.5` |
| Vector + lexical store | Neon Postgres + pgvector + tsvector FTS | Supabase、Aiven |
| Agent | hand-written ReAct → LangGraph(Wave 4) | LlamaIndex(Wave 7 对比) |
| Eval | hand-written + ragas;Wave 1d 后用 NVIDIA NIM judge | Gemini judge fallback |
| Tracing | Langfuse Cloud | — |
| Output validation | pydantic v2 | — |
| Guardrails(Wave 6) | NVIDIA NemoGuard + 自写 regex/PII | OpenAI Moderation |
| MCP(Wave 6) | 官方 `mcp` Python SDK 作为 server | — |
| API / UI | FastAPI + Streamlit | — |
| 部署 | Render / Fly.io 免费 tier | Railway;Cloudflare Worker(Wave 7 edge) |

Provider 切换由环境变量控制(`LLM_PROVIDER`、`EMBEDDING_PROVIDER`、`RERANKER_PROVIDER`),实现是单文件 `if/elif` 分发(规则 §3.1)。

---

## 6. Repo 布局

```
src/
  config.py               # env-driven settings
  llm.py                  # 3-provider closed-LLM dispatch (+NVIDIA NIM Wave 1d)
  embed.py                # 1-provider embedding (Wave 1a) → 3-provider (Wave 3f)
  db.py                   # psycopg connection + schema bootstrap        (Wave 1a)
  retrieve.py             # vector / FTS / hybrid / rerank               (Wave 1b → 3)
  rag.py                  # retrieve → prompt → answer (pydantic-typed)  (Wave 1b)
  ingest.py               # parse → split → embed → upsert               (Wave 1c)
  cli.py                  # CLI entry                                    (Wave 1c)
  rerank.py               # 2-provider reranker dispatch                 (Wave 3d)
  agent.py                # ReAct loop                                   (Wave 4)
  agent_lg.py             # LangGraph rewrite                            (Wave 4)
  tools/                  # 5 financial tools                            (Wave 4)
  api.py                  # FastAPI                                      (Wave 5A)
  ui.py                   # Streamlit                                    (Wave 5A)
  guardrails.py           # input/output filters                         (Wave 6)
  mcp_server.py           # expose tools as MCP server                   (Wave 6)
  financial/
    edgar.py              # EDGAR API + filing fetch                     (Wave 1c)
    table_extract.py      # table-aware ingestion                        (Wave 3b)
    schemas.py            # pydantic models for filings/chunks/answers   (Wave 1b → 1c)
prompts/                  # versioned prompt files (one per concern)
sql/                      # schema migrations
data/
  fixtures/               # tiny seeded snippets                         (Wave 1b)
eval/
  questions.jsonl         # 30–50 hand-curated Q&A                       (Wave 2)
  mini_eval.py            # 5–10 hand-eval                               (Wave 1.5)
  red_team.jsonl          # adversarial prompts                          (Wave 6)
  metrics.py
  run_eval.py
  reports/wave_<id>.md    # one report per metric-affecting wave
experiments/              # ablation scripts                             (Wave 3+)
runs/                     # agent traces (gitignored)                    (Wave 4)
tests/
edge/                     # Cloudflare Worker source                     (Wave 7)
```

显式不应出现的目录(出现即违反规则):`base/`、`factory/`、`providers/`、`domains/`、`plugins/`、`observability/`、`security/`。单文件分发优先。

---

## 7. Git 发布物格式(每个 wave 都遵守)

| Artifact | 格式 | 示例 |
|---|---|---|
| Branch | `wave/<id>-<short-name>` | `wave/1c-edgar-cli`、`wave/3c-hybrid-rrf` |
| Commit msg | `Wave <id>: <change> — <metric or result>` | `Wave 1c: EDGAR ingest CLI — AAPL 2024 filing ingests, answers with citations` |
| Tag | 轻量标签 `v0.<id>` | `v0.1c`、`v0.1.5`、`v0.5a` |
| Report | `eval/reports/wave_<id>.md`(影响指标的 wave 必交) | `eval/reports/wave_3c.md` |

---

## 8. Wave 详细执行手册

> **每个 wave 三段式:**
> 1. **学习先修**:开工前必须读完的资料 + 写进首 commit 的"假设"句
> 2. **实现**:具体代码工作 / 文档与配置改动 / git 产物
> 3. **验收**:`pytest` + 一条"冷克隆到可见结果"的命令

---

### Wave 0 — Foundation ✅ 已交付(commit `ac0da4e`)

#### 学习先修
- **必读**:Gemini / Anthropic / OpenAI SDK quickstart 三份;LLM Engineer §1 Running LLMs(API 部分)。
- **重点**:三家如何返回 token usage、错误码差异、stream 接口形状。
- **假设(写进首 commit)**:"我假设三家 SDK 在 chat completion 接口上语义差异有限,可以用一个 `LLMResponse` 统一形状 + 单文件 `if/elif` 分发。第二个变种(NVIDIA NIM)出现时再考虑是否需要更高抽象。"

#### 实现
- **代码**:
  - `src/config.py` —— env-driven 设置
  - `src/llm.py` —— 3-provider closed-LLM dispatch + `LLMResponse`
  - `tests/test_llm.py` —— 三家 smoke test,无 key 时 skip
- **文档/配置**:README 状态行 Wave 0 ✅;`.env.example` 含 3 个 closed-provider key + Wave 1d 用的 `NVIDIA_API_KEY` 占位。
- **Git**:branch `wave/0-foundation`,tag `v0.0`,commit `ac0da4e`。无 eval 报告(Wave 2 未到)。

#### 验收
```bash
GEMINI_API_KEY=xxx uv run pytest -k gemini      # passes
```

---

### Wave 1a — Postgres + pgvector schema + NVIDIA embedding(~1 天)

#### 学习先修
- **必读**:pgvector 文档(HNSW 三参数 `m`、`ef_construction`、`ef_search`;cosine vs L2 距离);Neon free tier + branching 文档;NVIDIA NeMo Retriever embedding API 文档。
- **配套**:LLM Engineer §2 Building a Vector Storage(向量库 + embedding 部分)。
- **假设示例**:"我假设 768d + HNSW(m=16, ef_construction=64)足以覆盖 5–10 家公司的 chunk 数量级,不需要 IVF;若 wave 2 测出 recall@10 < 0.5,需要回退尝试 ef_search 调高或换索引类型。"

#### 实现
- **代码**:
  - `sql/001_init.sql` —— schema(见下,幂等)
  - `src/db.py` —— psycopg3 连接 + schema bootstrap
  - `src/embed.py` —— 单 provider(NVIDIA);多 provider 比较推迟到 Wave 3f
- **文档/配置**:README 状态 Wave 1a → in_progress;`.env.example` 已含 `DATABASE_URL`、`NVIDIA_API_KEY`、`EMBEDDING_PROVIDER=nvidia`、`EMBEDDING_MODEL=nvidia/nv-embedqa-e5-v5`。
- **Git**:branch `wave/1a-pgvector-schema` → tag `v0.1a`。本 wave 无 eval 报告。

#### 验收
```bash
psql "$DATABASE_URL" -f sql/001_init.sql        # idempotent — run twice, no errors
uv run python -c "from src.embed import embed; print(len(embed(['hello world'])[0]))"
# → 768
uv run pytest -q
```

#### Schema(`sql/001_init.sql`)

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

---

### Wave 1b — Dense retrieval + 带引用的 Answer(本地 fixture,~2 天)

#### 学习先修
- **必读**:RAG 论文(Lewis 2020)§3;pydantic v2 的 `model_validate`;**为什么必须让 LLM 返回 citation ID**(防幻觉契约)。
- **配套**:LLM Engineer §2 + §3 RAG basics。
- **假设示例**:"我假设让 LLM 输出严格 JSON Answer 并校验 citation 指向真实 chunk_id,可以把表层幻觉抓住一大半;若 mini-eval 显示 citation 有效率 < 80%,说明 prompt 模板需要改写,而不是检索的问题。"

#### 实现
- **代码**:
  - `src/retrieve.py` —— dense top-k,可选 `WHERE ticker/period` 过滤
  - `src/rag.py` —— retrieve → prompt → 调 LLM → pydantic `Answer`;citation 不指向真实 chunk_id 直接 reject
  - `src/financial/schemas.py` —— 最小集合 `Citation`、`Answer`
  - `data/fixtures/` + 一个最简 seed 脚本
  - `prompts/answer_v1.txt` —— 版本化 prompt(规则:每次改 prompt 必须改文件名 / 在 git 留痕)
- **文档/配置**:README 状态 Wave 1b in_progress;Wave 1b 起开始建 `eval/reports/wave_<id>.md`,记录 prompt SHA。
- **Git**:branch `wave/1b-cited-rag` → tag `v0.1b` → `eval/reports/wave_1b.md`(列出 fixture、prompt SHA、样例 Q/A)。

#### 验收
```bash
uv run python -m src.rag --ticker DEMO "what was revenue?"
# → JSON Answer with citations[*].chunk_id all present in chunks table
uv run pytest -q   # includes RAG round-trip + hallucinated-citation rejection
```

---

### Wave 1c — EDGAR ingestion + CLI(~2 天)

#### 学习先修
- **必读**:SEC EDGAR API:`submissions/CIK*.json`、accession number 含义、10-K `<DOCUMENT>` 结构;**为什么 fixed-token chunking 是低天花板**(为 Wave 3a/3b 留动机,但**这一 wave 先不修**)。
- **配套**:LLM Engineer §3 RAG ingestion(document loaders、splitters)。
- **假设示例**:"我假设 1000-token 固定切分 + 简单 strip 解析在本 wave 已足以让 `finrag ask` 端到端跑通;表格 / 数值类问题精度不足是已知问题,留给 Wave 3b。"

#### 实现
- **代码**:
  - `src/financial/edgar.py` —— filing fetch,起步 hard-code ticker 列表
  - `src/financial/schemas.py` —— 扩 `Filing`、`Chunk`
  - `src/ingest.py` —— download → strip → 1000-token chunks → embed → upsert
  - `src/cli.py` —— `finrag ingest`、`finrag ask`
- **文档/配置**:README 状态 Wave 1c;README "Quick start" 增 `finrag ingest`/`ask` 示例。
- **Git**:branch `wave/1c-edgar-cli` → tag `v0.1c` → `eval/reports/wave_1c.md`(每 filing 行数、样例答案 + citation 链路截图)。

#### 验收
```bash
uv sync --group dev && cp .env.example .env       # fill GEMINI_API_KEY + DATABASE_URL + NVIDIA_API_KEY
uv run finrag ingest --tickers AAPL --year 2024
# → "ingested 1 document, N chunks"
uv run finrag ask --ticker AAPL --year 2024 "What was Apple's R&D expense?"
# → cited Answer (≥ 1 citation pointing to a real chunk)
uv run pytest -q
```

---

### Wave 1d — NVIDIA NIM 作为 cloud open-weight provider(~0.5 天)

#### 学习先修
- **必读**:OpenAI-compatible endpoint 模式;NVIDIA NIM 在 `https://integrate.api.nvidia.com/v1` 的模型目录与速率限制。
- **配套**:LLM Engineer §1 Running LLMs(open-weight 部分,顺带读 Together / Groq 对比)。
- **假设示例**:"我假设把 NVIDIA NIM 接进来后,用同一组测试问题在 closed vs open-weight 上对比,会暴露出 prompt 对模型敏感度问题;若答案相似度极高,意味着我的题目区分度不够,需要 Wave 2 重新设计 eval 集。"

#### 实现
- **代码**:
  - `src/config.py` —— 注册 `nvidia` provider + `NVIDIA_API_KEY`
  - `src/llm.py` —— 加 `_chat_nvidia()` 分支,用 OpenAI-compatible base URL
  - `tests/test_llm.py` —— NVIDIA smoke test,无 key skip
- **文档/配置**:README 技术栈表去掉 NVIDIA 行的 *planned* 标记;`llm.py` 描述改为"4-provider";`.env.example` 把 `NVIDIA_API_KEY` 从占位改为 active。
- **Git**:branch `wave/1d-nvidia-nim` → tag `v0.1d`。可选报告:若 closed vs open-weight 答案差异显著,写一份对比记录。

#### 验收
```bash
LLM_PROVIDER=nvidia LLM_MODEL=meta/llama-3.1-70b-instruct \
  uv run pytest tests/test_llm.py -k nvidia
LLM_PROVIDER=nvidia uv run finrag ask --ticker AAPL --year 2024 "..."
```

---

### Wave 1.5 — Mini-eval(~0.5 天)★ 关卡

这一 wave 是 *能跑* 与 *知道效果* 之间的分水岭。在 Wave 2 正式 harness 之前,先做一次轻量手评。

#### 学习先修
- **必读**:RAGAS 论文(Es 2023)§3 指标定义;**怎么写一道"在 filing 里有唯一可辩护答案"的紧凑题目**。
- **配套**:LLM Engineer §3 RAG eval。
- **假设示例**:"我假设当前 baseline 在 5–10 道手工题上 retrieval hit-rate ≥ 70%、citation 有效率 ≥ 80%;若任一不达标,说明 chunking / prompt 二者之一已是瓶颈。"

#### 实现
- **代码**:
  - `eval/mini_eval.py` —— 加载 5–10 条 `(question, expected_doc_id, notes)`,跑 RAG,打印 retrieval hit + citation validity + 人工 pass/fail prompt
  - `eval/reports/wave1_5_mini_eval.md` —— 实际报告(本 wave 的核心交付物)
- **文档/配置**:README 状态:插入 Wave 1.5 行;Wave 1 的 metrics 列填上 baseline 数字。
- **Git**:branch `wave/1.5-mini-eval` → tag `v0.1.5` → `eval/reports/wave1_5_mini_eval.md`。

#### 验收
```bash
uv run python eval/mini_eval.py
# → table of 5–10 items: retrieval hit-rate, citation validity %, human pass/fail
# → eval/reports/wave1_5_mini_eval.md committed
```

---

### Wave 2 — Eval harness(~3 天)★ 关键

#### 学习先修
- **必读**:recall@k / MRR / nDCG 定义(信息检索教材任一章节);LLM-as-judge bias 文献(如 Zheng 2023);**为什么便宜的 judge 模型对相对比较已经够用**。
- **配套**:LLM Engineer §3 RAG eval(faithfulness、answer-relevancy 部分)。
- **假设示例**:"我假设 30–50 道覆盖 5 个类别的题目,recall@10 / faithfulness 两个指标已经能稳定 ranking 各种 retrieval 改动;同一份 eval 跑两次方差应该 < 0.02,否则 judge 不稳。"

#### 实现
- **代码**:
  - `eval/questions.jsonl` —— 30–50 条 `(question, expected_doc_ids, expected_answer, category)`,5 类:numeric、table、cross-document、reasoning、consistency
  - `eval/metrics.py` —— retrieval(recall@k / mrr / ndcg);generation(faithfulness + answer-relevancy via NVIDIA NIM judge,Gemini `gemini-2.5-flash-lite` 兜底)
  - `eval/run_eval.py` —— 完整跑 → `eval/reports/wave_2.md`(每题 + 每类汇总,记录 prompt SHA)
- **文档/配置**:README 状态 Wave 2;README headline metric 列首次填入真实数字。
- **Git**:branch `wave/2-eval-harness` → tag `v0.2` → `eval/reports/wave_2.md`(Wave 1 baseline)。

#### 验收
```bash
uv run python eval/run_eval.py
# → eval/reports/wave_2.md committed; recall@10 / faithfulness shown
uv run python eval/run_eval.py   # rerun: numbers within ±0.02 of committed report
```

---

### Wave 3 — Retrieval quality(~1 周)★ ablation 展示

每个子步骤 = 一个 commit + 一份报告 + 一行 README ablation 表。

| Step | PRD increment | 主要改动 | 期望提升 |
|---|---|---|---|
| 3a | 叙事 chunking 不再被截断 | fixed → semantic(sentence-window)→ hierarchical / parent-doc | recall@10 ↑ |
| 3b | 数值题不再因为表格被切碎而漏 | table-aware ingestion(Docling / unstructured),表格作为独立 chunk + 序列化 schema | numeric accuracy ↑ |
| 3c | 词汇精确查询(缩写、原文短语)开始能命中 | hybrid:`pgvector + tsvector` 在一个 SQL CTE 里 RRF 融合 | recall@10 ↑ |
| 3d | top-1 答案相关性提升,不动检索 | NVIDIA NeMo Retriever rerank,top-50 → top-10 | faithfulness ↑、MRR ↑ |
| 3e | under-specified 查询能用 | query rewriting(ticker/year/unit 规整、multi-query、HyDE 对比);**含 retriever variants:metadata filter + parent-doc + multi-query** | under-specified recall ↑ |
| 3f | 知道 embedding 选择是否重要 | NVIDIA vs Gemini vs Voyage vs Cohere | data point |

#### 学习先修(整个 Wave 3 共享)
- **必读**:LLM Engineer §4 Advanced RAG 全章;RRF 论文(Cormack 2009);NVIDIA NeMo Retriever rerank 文档。
- **每个 sub-step 单独写一句假设** 进对应 commit,例如 3c:"我假设 pgvector + tsvector RRF 融合在缩写 / 数字代号题目上 recall@10 提升 ≥ 0.05;若提升 < 0.02,说明 BM25 权重需要调或 fusion 公式需要换。"

#### 实现
- 每个 step 一个 `experiments/wave3_<letter>_<name>.py` + `src/retrieve.py` 里一个 feature flag(支持 A/B)。
- 用 Neon DB branch 隔离每个 step 的实验数据。

#### 文档/配置
- README 增加一张 6 行 ablation 表(指标 delta + commit hash)。

#### Git
- 6 个 branch `wave/3a-…` … `wave/3f-…`,6 个 tag `v0.3a` … `v0.3f`,6 份报告 `eval/reports/wave_3a.md` … `wave_3f.md`。

#### 验收(每个 step 独立验收)
```bash
uv run python eval/run_eval.py    # 数字提升,或在报告里说明为什么没提升
```

---

### Wave 4 — Agent + tools(~1 周)

#### 学习先修
- **必读**:ReAct 论文(Yao 2022);tool-calling JSON schema(OpenAI 格式);Anthropic [Building effective agents](https://www.anthropic.com/research/building-effective-agents);LangGraph quickstart。
- **配套**:LLM Engineer §5 Agents 全章。
- **重点心态**:这一 wave 必须**亲手写 ReAct loop**,即使 nanobot / LangChain 等框架可以一键搞定。这是项目最重要的简历价值,框架 wrap 在 Wave 7 才考虑。
- **假设示例**:"我假设 5 个工具(retrieve_filing / lookup_metric / compare_companies / web_search / calculator)足以覆盖 80% 多步研究题;agent 在 ≤ 6 步内的 task success rate 应该 ≥ 60%。若低于 40%,说明工具粒度划分有问题。"

#### 实现
- **代码**:
  - `src/tools/` —— `retrieve_filing`、`lookup_metric`(XBRL / 派生 `metrics` 表)、`compare_companies`、`web_search`(Tavily 免费 tier)、`calculator`
  - `src/agent.py` —— 手写 ReAct loop,完整 trace JSONL 写到 `runs/<id>.jsonl`
  - `src/agent_lg.py` —— 同一个 loop 在 LangGraph 重写一遍(对比体感)
  - `eval/agent_questions.jsonl` —— 15–20 条多步任务
  - **Memory(填补 mlabonne 缺口)**:`agent.py` 加最简 session memory(最近 N 个 Q/A 作为上下文)。Long-term memory 推迟到 Wave 7。
- **文档/配置**:README 状态 Wave 4;`.env.example` 加 `TAVILY_API_KEY`(已有)。
- **Git**:branch `wave/4-react-agent` → tag `v0.4` → `eval/reports/wave_4.md`(task success rate、tool-call accuracy、平均步数);LangGraph A/B 单独 `eval/reports/wave_4_langgraph_compare.md`。

#### 验收
```bash
uv run python -m src.agent "How did NVDA's R&D-to-revenue ratio change vs AMD between FY2022 and FY2024?"
# → final answer + runs/<id>.jsonl with each tool call replayable
uv run python eval/run_eval.py --suite agent
```

---

### Wave 5A — Public demo(~3 天)

#### 学习先修
- **必读**:FastAPI streaming 基础(SSE);Streamlit 单页 Q&A 模式;Render free-tier 部署文档。
- **配套**:LLM Engineer §7 Deploying LLMs(server / demo 部分)。
- **假设示例**:"我假设 Streamlit + FastAPI 在 Render 免费 tier 冷启动 < 30s,p50 query latency < 8s 是可接受门槛;若超过,需要先做 Wave 5B 的 streaming 才能接受公网 demo。"

#### 实现
- **代码**:
  - `src/api.py` —— `POST /ask`(SSE stream)、`POST /ingest`、`GET /health`
  - `src/ui.py` —— Streamlit 单页 Q&A,citation 可悬停 / 点击
  - 部署配置(Render `render.yaml` 或 Fly `fly.toml`)
- **文档/配置**:README "Quick start" 加一行公开 demo URL("**Try it**: https://finrag-demo.onrender.com")。
- **Git**:branch `wave/5a-public-demo` → tag `v0.5a`。可选报告:若部署延迟与本地差异显著,写延迟对比。

#### 验收
```bash
uv sync --group dev
uv run uvicorn src.api:app --host 0.0.0.0 --port 8000
uv run streamlit run src/ui.py
# → browser opens Streamlit; ask an AAPL question, see answer + citations; /health → OK
# → public URL serves the same flow
```

---

### Wave 5B — Observability / cost / streaming / caching(~4 天)

#### 学习先修
- **必读**:Anthropic ephemeral cache + Gemini explicit cache API 文档;Langfuse Python SDK quickstart;SSE backpressure 入门。NVIDIA prompt-cache **不预设支持**,本 wave 实现时去 NIM 文档现查。
- **配套**:LLM Engineer §6 Inference Optimization + §7 observability。
- **假设示例**:"我假设把 system prompt + tool schemas 进 ephemeral cache 后,p50 latency 降 ≥ 30%、$/query 降 ≥ 40%;若低于一半,说明 cache hit rate 没起来,需要查 cache key 是否变动太频繁。"

#### 实现
- **代码**:
  - `chat()`、`retrieve()`、agent 步骤外面包 Langfuse spans(每个请求一个 `trace_id`)
  - Anthropic ephemeral cache 包 system prompt + tool schemas;Gemini explicit cache 包分块 filing context
  - per-request token + USD 估算表写进 eval 报告
- **文档/配置**:README headline metric 列(Wave 5B)填 p50 latency + $/query before/after;`.env.example` 已有 `LANGFUSE_*`。
- **Git**:branch `wave/5b-obs-cost` → tag `v0.5b` → `eval/reports/wave_5b.md`(caching delta、latency 直方图、cost-per-query)。

#### 验收
```bash
uv run finrag ask --ticker AAPL --year 2024 "..."
# → Langfuse trace appears within 5s of call; trace shows retrieve span + chat span + tool spans
# → eval/reports/wave_5b.md shows latency_p50_before / _after, cost_before / _after
```

---

### Wave 6 — Security & MCP(~1 周)

#### 学习先修
- **必读**:prompt-injection 类型学(direct / indirect / cross-language);NVIDIA NemoGuard content-safety + jailbreak-detection 文档;MCP 规范(stdio transport + tool schema 部分)。
- **配套**:LLM Engineer §8 Securing LLMs。
- **假设示例**:"我假设 25–30 条对抗 prompt 在无防御时 ASR(attack success rate)≥ 50%;接入 NemoGuard + 自写 regex/PII 后 ASR 降到 ≤ 15%;若降不下来,说明 indirect injection(filing 里塞攻击文本)是主漏口,需要在 retrieval 阶段过滤。"

#### 实现
- **代码**:
  - `src/guardrails.py` —— `screen_input`、`redact_pii`、`validate_output`,主路径走 NVIDIA NemoGuard,OpenAI Moderation 备份
  - `eval/red_team.jsonl` —— 25–30 条对抗 prompt × 5 类(direct jailbreak / system-prompt extraction / citation manipulation / indirect injection via planted chunk / Chinese attack)
  - `eval/run_red_team.py`
  - `src/mcp_server.py` —— 官方 `mcp` Python SDK,stdio transport
- **文档/配置**:README 增 "Use finrag as an MCP tool from Claude Desktop" 段;状态 Wave 6 + ASR delta。
- **Git**:branch `wave/6-security-mcp` → tag `v0.6` → `eval/reports/wave_6.md`(ASR before/after,按类细分);raw run 单独 `eval/reports/wave_6_redteam_<timestamp>.md`。

#### 验收
```bash
uv run python eval/run_red_team.py        # before defenses
# turn defenses on
uv run python eval/run_red_team.py        # after — ASR drops
uv run python -m src.mcp_server | mcp-inspector --stdio  # tools/list works
# add server to Claude Desktop config; ask "what was AAPL revenue?" — answers via MCP
```

---

### Wave 7 — Extensions(自选,按简历价值挑 2–4 个)

每条独立。**不要全做。**每条 DoD:一个 commit、一份 `eval/reports/` 报告、一行简历 bullet。Branch / tag 沿用 §7 格式。

| 编号 | 项目 | 选它的理由 |
|---|---|---|
| 7.lli | LlamaIndex orchestrator 对比 | 证明你能读别人的框架,不只能写自己的 |
| 7.dspy | DSPy `BootstrapFewShot` 优化某条 prompt | mlabonne "Program LLMs" 覆盖 |
| 7.crew | CrewAI / Smolagents port agent | agent 框架广度 |
| 7.edge | Cloudflare Worker edge demo(`edge/worker.ts`) | 边缘部署技能,无需本地基础设施 |
| 7.sql | NL → EDGAR XBRL / SQL(text-to-SQL) | 填 mlabonne 缺口;数值题不该走 RAG |
| 7.mem | 对话 + episodic memory | 填 mlabonne "Memory" 缺口;per-session + 长期摘要 |
| 7.crit | self-correction critic loop | citation / 数值校验后再 prompt 一次;faithfulness ↑ |
| 7.bil | 双语 report mode(`finrag report`) | 商业化 MVP |
| 7.cn | CN A 股年报 | 商业化差异化 |
| 7.ci | CI eval gates(GitHub Action) | 填 mlabonne "Regression eval" 缺口;PR 让 recall@10 跌 > 0.02 即失败 |
| **7.nanobot** | **finrag-as-MCP × nanobot 多渠道部署** | **Wave 6 MCP server 的真实第三方消费验证;同时拿到一个 Slack/Discord 部署的简历项** |

#### Sub-wave 7.nanobot 详情(approved 方案专用)

- **前置**:Wave 6 MCP server 已稳定。
- **学习先修**:nanobot README + WebUI 文档;选定渠道(推荐 Slack 或 Discord)的 bot 注册流程;**重点理解 nanobot 是 MCP client,而 finrag 的 MCP server 是被调用方**。
- **假设示例**:"我假设我的 finrag MCP server 接口能被一个完全独立的 agent 框架(nanobot)在不改我代码的情况下消费;若 nanobot 接入时需要我改 MCP server,说明 Wave 6 的 tool schema 设计有耦合问题。"
- **实现**:
  - 在 `experiments/nanobot/` 起一个 nanobot 实例(独立目录,200–400 行 glue + 配置)
  - 配置 nanobot 的 MCP client 指向 Wave 6 的 finrag MCP server
  - 选 1 个渠道首发(Slack 海外友好 / Feishu 国内场景差异化)
  - system prompt 把 nanobot 配置成"金融披露问答助手",约束只通过 finrag tools 回答
- **Git**:branch `wave/7-nanobot` → tag `v0.7nanobot` → `eval/reports/wave_7_nanobot.md`(接入耗时、暴露的 MCP 接口缺陷、$/query)。
- **验收**:
  ```bash
  # 在选定渠道 @ bot 提问,如 "What was AAPL's revenue in FY2023?"
  # → 返回 Answer + citations,citation 链接到 SEC 文件原文片段
  # → 至少 5 个真实问题闭环成功
  ```
- **简历 bullet 模板**:"Exposed finrag retrieval/agent tools as an MCP server consumed by an external agent framework (nanobot), deployed as a Slack bot answering SEC filing questions with citations."

---

## 9. 端到端项目验证(Wave 5A 之后)

一个新协作者只有 `GEMINI_API_KEY` 和 `DATABASE_URL`,应该能完成:

1. `git clone …` → `uv sync --group dev` → `cp .env.example .env`(填 2 个 key)
2. `uv run finrag ingest --tickers AAPL,MSFT --year 2024`
3. `uv run finrag ask --ticker AAPL "FY2024 R&D 支出"` → 带 citation 的答案
4. `uv run python eval/run_eval.py` → 数字与 Wave 2 报告差 ±0.02 内
5. 打开公开 demo URL,跑同样的查询,看到等价答案
6. Wave 5B 之后:从第 5 步反查到对应 Langfuse trace

任一步失败 → 拥有该步骤的 wave 状态回退到 in_progress。

---

## 10. 不在范围内(以及为什么)

- **Flash Attention / KV cache 内核 / speculative decoding** —— 模型内部;需要单独 vLLM/TGI 项目。
- **真正的本地模型部署** —— 用户主动选择排除。
- **后门研究(训练时攻击)** —— 属于 LLM Scientist track。

---

## 11. 工作笔记

- 计划 delta 进 `git log execution.md`,不另起文件。
- 原始 brainstorm 在 `~/.claude/plans/rag-copilot-rag-agent-snoopy-goose.md`,**仅作存档**;本文件取代它。
- 2026-05-07 改写要点:文件改为单一中文 wave-by-wave 执行手册;每个 wave 强制三段式(学习先修 / 实现 / 验收);把 Wave 7 sub-item `7.nanobot` 与 LLM Engineer 章节地图正式纳入(原 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) × [mlabonne/llm-course](https://github.com/mlabonne/llm-course) 整合方案)。
