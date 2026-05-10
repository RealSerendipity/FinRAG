# Wave 1b — Dense retrieval + cited answer

## Fixture

- Ticker: `DEMO`, Period: `FY2024` (fixture seed; legacy format predates YYYY-MM-DD period contract)
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

- Citation `chunk_id` resolves to a real chunk on all 3 questions; hallucination check passes in every case.
- LLM quote fidelity: Q1 and Q3 quote nearly verbatim; Q2 truncates slightly (drops "up from $1.8 billion"). This shows chunk_id existence checks alone cannot guarantee quote completeness — a faithfulness metric is needed (Wave 2).
- All 3 questions hit the correct chunk (chunk_id matches question content one-to-one); dense retrieval on a small fixture behaves as expected.

## Theory ↔ Practice

**Assumption:** Having the LLM return a `chunk_id` and validating its existence at the API layer
blocks the coarsest form of hallucination (citing a non-existent source) while giving users a
traceable reference to the original text.

**Observed:** Gemini 2.5 Flash achieves 100% chunk_id accuracy on a 3-chunk fixture, but quotes
are occasionally truncated. Citation checks are effective at the "source traceability" level but
insufficient at the "quote completeness" level — faithfulness evaluation is required.
Wave 1.5 mini-eval and the Wave 2 harness will quantify this gap using real EDGAR data.
