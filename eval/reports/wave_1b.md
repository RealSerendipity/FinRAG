# Wave 1b — Dense retrieval + cited answer

## Fixture

- Ticker: `DEMO`, Period: `FY2024`
- 3 chunks seeded via `data/fixtures/seed.py`
- document `id=1` in Neon Postgres

| chunk_id | content summary |
|---|---|
| 1 | Total revenue $12.5B, +8% YoY |
| 2 | R&D expense $2.1B (up from $1.8B) |
| 3 | Net income $3.2B, profit margin 25.6% |

## Prompt

- File: `prompts/answer_v1.txt`
- SHA: `b240459717a6382c27297e41d396dd2696d3ec8b`

## Sample Q/A

**Q1:** What was DEMO Corp's revenue in FY2024?

**A:** DEMO Corp's total revenue for fiscal year 2024 was $12.5 billion, which was an 8% increase compared to fiscal year 2023.

**Citations:**
- `chunk_id=1`: "DEMO Corp reported total revenue of $12.5 billion for fiscal year 2024, representing a 8% increase compared to fiscal year 2023."

---

**Q2:** What was DEMO Corp's R&D expense in FY2024?

**A:** DEMO Corp's research and development expenses for fiscal year 2024 were $2.1 billion.

**Citations:**
- `chunk_id=2`: "Research and development expenses for fiscal year 2024 were $2.1 billion"

---

**Q3:** What was DEMO Corp's net profit margin in FY2024?

**A:** DEMO Corp's net profit margin for fiscal year 2024 was approximately 25.6% on total revenues.

**Citations:**
- `chunk_id=3`: "Net income for fiscal year 2024 was $3.2 billion, yielding a net profit margin of approximately 25.6% on total revenues."

## Observations

- Citation `chunk_id` 在所有 3 道题上均指向真实存在的 chunk，hallucination 检查全部通过。
- LLM 对 quote 字段的处理：Q1 和 Q3 基本逐字引用原文；Q2 做了轻微截断（去掉了后半段"up from $1.8 billion"）。说明 quote 的完整性无法靠 chunk_id 检查保证，需要 Wave 2 的 faithfulness 指标量化。
- 3 道题全部命中正确 chunk（chunk_id 与问题内容一一对应），dense retrieval 在小 fixture 上表现符合预期。

## Theory ↔ Practice

假设：让 LLM 返回 chunk_id 并做存在性校验，可以把最粗粒度的幻觉（引用不存在的来源）阻断在 API 层，同时让用户有原文可查。

实测：Gemini 2.5 Flash 在 3 条 chunk 的 fixture 上 chunk_id 准确率 100%，但 quote 有时截断原文。这说明 citation 检查在"来源可追溯"层面有效，在"引用完整性"层面需要额外的 faithfulness 评估。Wave 1.5 mini-eval 和 Wave 2 harness 将用真实 EDGAR 数据量化这个差距。
