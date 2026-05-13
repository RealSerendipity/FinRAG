# Wave 1.5 — Mini-eval report

- Corpus: AAPL FY2024 10-K (period `2024-09-28`)
- Items: 7 (6 positive + 1 insufficient-context)
- `top_k = 5`, ground-truth probe `K_max = 50`
- LLM provider: `nvidia` / model: `meta/llama-3.3-70b-instruct`
- Judge provider: `nvidia` / model: `meta/llama-3.1-70b-instruct`
- Embedding: NVIDIA NeMo Retriever `nv-embedqa-e5-v5`

## Headline metrics (means over positive items unless noted)

- **hit@5**: 0.83
- **recall@5**: 0.49
- **MRR**: 0.75
- **nDCG@5**: 0.52
- **citation validity** (all items, structural): 0.71
- **faithfulness** (LLM-judge over 4/6 positive answers): 1.00

Ground-truth relevance is approximated by OR-of-AND keyword groups, so `recall@k` and `nDCG@k` use a local denominator (relevants found within top-50). MRR is the reciprocal rank of the first relevant chunk in that top-50 probe; 0 when nothing relevant surfaces. Citation validity is structural: positive items must cite a chunk that matches the relevance predicate; negative items must declare exactly `"Insufficient context"` with no citations.

Caveats: n=7 over a single 10-K — these numbers are illustrative, not a recall benchmark. Wave 2's harness widens to 30–50 curated items with category coverage and stability checks.

## Per-item results

| id | hit@5 | recall@5 | MRR | nDCG@5 | citation valid | faithful | total relevant in top-50 |
|---|---|---|---|---|---|---|---|
| `aapl-fy24-total-net-sales` | yes | 0.60 | 1.00 | 0.70 | yes | yes | 5 |
| `aapl-fy24-iphone-net-sales` | yes | 1.00 | 1.00 | 1.00 | yes | yes | 2 |
| `aapl-fy24-rd` | yes | 0.50 | 0.33 | 0.31 | yes | yes | 2 |
| `aapl-fy24-iphone16-launch` | yes | 0.50 | 1.00 | 0.61 | no | not judged | 2 |
| `aapl-fy24-dividend-per-share` | no | 0.00 | 0.14 | 0.00 | no | not judged | 1 |
| `aapl-fy24-tax-rate-risk` | yes | 0.33 | 1.00 | 0.51 | yes | yes | 6 |
| `aapl-fy24-argentina-revenue-insufficient` | — | — | — | — | yes | — | 0 |

## Answers + judge reasons

### `aapl-fy24-total-net-sales`

**Question.** What were Apple's total net sales for fiscal year 2024?

**Expected.** Apple FY2024 total net sales: $391,035M.

**Retrieved top-5 chunk_indexes.** [82, 107, 108, 81, 83]

**Relevant ranks in top-50.** [1, 2, 4, 6, 10]

**Answer.** Apple's total net sales for fiscal year 2024 were $391,035

**Cited chunk_indexes.** [82]

**Judge faithfulness.** True — Answer directly matches cited total net sales figure.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-iphone-net-sales`

**Question.** What were Apple's iPhone net sales in fiscal year 2024?

**Expected.** iPhone FY2024 net sales: $201,183M.

**Retrieved top-5 chunk_indexes.** [82, 107, 81, 83, 108]

**Relevant ranks in top-50.** [1, 2]

**Answer.** Apple's iPhone net sales in fiscal year 2024 were $201,183 million

**Cited chunk_indexes.** [82]

**Judge faithfulness.** True — Directly supported by the cited table.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-rd`

**Question.** How much did Apple spend on research and development in fiscal year 2024?

**Expected.** R&D expense FY2024: $31,370M.

**Retrieved top-5 chunk_indexes.** [85, 87, 95, 83, 119]

**Relevant ranks in top-50.** [3, 18]

**Answer.** Apple spent $31,370 million on research and development in fiscal year 2024.

**Cited chunk_indexes.** [95]

**Judge faithfulness.** True — Answer directly matches cited data.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-iphone16-launch`

**Question.** Which iPhone 16 models did Apple release during fiscal year 2024?

**Expected.** iPhone 16, 16 Plus, 16 Pro, 16 Pro Max.

**Retrieved top-5 chunk_indexes.** [80, 79, 82, 107, 87]

**Relevant ranks in top-50.** [1, 12]

**Answer.** Insufficient context

**Cited chunk_indexes.** []

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-dividend-per-share`

**Question.** What quarterly cash dividend per share did Apple declare during fiscal 2024?

**Expected.** Quarterly dividend: $0.25 per share.

**Retrieved top-5 chunk_indexes.** [102, 99, 119, 108, 94]

**Relevant ranks in top-50.** [7]

**Answer.** Insufficient context

**Cited chunk_indexes.** []

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-tax-rate-risk`

**Question.** What risks does Apple identify around changes in its effective tax rate?

**Expected.** Risk factors mention tax-rate changes, new tax legislation, and additional liabilities.

**Retrieved top-5 chunk_indexes.** [67, 91, 68, 93, 63]

**Relevant ranks in top-50.** [1, 3, 8, 12, 21, 32]

**Answer.** Apple identifies risks around changes in its effective tax rate, including changes in tax laws or their interpretation, and the introduction of new taxes.

**Cited chunk_indexes.** [67]

**Judge faithfulness.** True — All claims are directly supported by the cited chunks.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-argentina-revenue-insufficient`

**Question.** What were Apple's net sales in Argentina in fiscal year 2024?

**Expected.** 10-K breaks geography by Americas/Europe/Greater China/Japan/Rest of Asia Pacific — no country-level Argentina figure.

**Retrieved top-5 chunk_indexes.** [82, 81, 107, 137, 139]

**Relevant ranks in top-50.** []

**Answer.** Insufficient context

**Cited chunk_indexes.** []

**Human pass/fail.** _TBD — fill in after review._

## Theory ↔ Practice

RAGAS (Es 2023) separates retrieval and generation axes. This mini-eval covers retrieval with hit@k / recall@k / MRR / nDCG@k under an approximate keyword ground truth, and generation with a structural citation check plus an LLM-judge faithfulness pass. The single-judge setup inherits bias risks discussed in Zheng 2023; Wave 2 will add a second-judge sanity check and stability across re-runs. ragas itself is intentionally not wired here — it is a Wave-2 dependency choice alongside the bigger 30–50 item set.
