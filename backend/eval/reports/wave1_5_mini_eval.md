# Wave 1.5 — Mini-eval report

- Corpus: AAPL FY2024 10-K (period `2024-09-28`)
- Items: 7 (6 positive + 1 insufficient-context)
- `top_k = 5`, ground-truth probe `K_max = 50`
- LLM provider: `nvidia` / model: `meta/llama-3.3-70b-instruct`
- Judge provider: `nvidia` / model: `nvidia/llama-3.3-nemotron-super-49b-v1`
- Embedding: NVIDIA NeMo Retriever `nv-embedqa-e5-v5`

## Headline metrics (means over positive items unless noted)

- **hit@5**: 1.00
- **recall@5**: 0.87
- **MRR**: 0.92
- **nDCG@5**: 0.88
- **citation validity** (all items, structural): 1.00
- **faithfulness** (LLM-judge over 6/6 positive answers): 1.00

Ground-truth relevance is approximated by OR-of-AND keyword groups, so `recall@k` and `nDCG@k` use a local denominator (relevants found within top-50). MRR is the reciprocal rank of the first relevant chunk in that top-50 probe; 0 when nothing relevant surfaces. Citation validity is structural: positive items must cite a chunk that matches the relevance predicate; negative items must declare exactly `"Insufficient context"` with no citations.

Caveats: n=7 over a single 10-K — these numbers are illustrative, not a recall benchmark. Wave 2's harness widens to 30–50 curated items with category coverage and stability checks.

## Per-item results

| id | hit@5 | recall@5 | MRR | nDCG@5 | citation valid | faithful | total relevant in top-50 |
|---|---|---|---|---|---|---|---|
| `aapl-fy24-total-net-sales` | yes | 0.80 | 0.50 | 0.66 | yes | yes | 5 |
| `aapl-fy24-iphone-net-sales` | yes | 1.00 | 1.00 | 1.00 | yes | yes | 2 |
| `aapl-fy24-rd` | yes | 1.00 | 1.00 | 1.00 | yes | yes | 2 |
| `aapl-fy24-iphone16-launch` | yes | 1.00 | 1.00 | 0.92 | yes | yes | 2 |
| `aapl-fy24-dividend-per-share` | yes | 1.00 | 1.00 | 1.00 | yes | yes | 1 |
| `aapl-fy24-tax-rate-risk` | yes | 0.43 | 1.00 | 0.68 | yes | yes | 7 |
| `aapl-fy24-argentina-revenue-insufficient` | — | — | — | — | yes | — | 0 |

## Answers + judge reasons

### `aapl-fy24-total-net-sales`

**Question.** What were Apple's total net sales for fiscal year 2024?

**Expected.** Apple FY2024 total net sales: $391,035M.

**Retrieved top-5 chunk_indexes.** [108, 82, 107, 139, 81]

**Relevant ranks in top-50.** [2, 3, 4, 5, 7]

**Answer.** Apple's total net sales for fiscal year 2024 were $391,035 million

**Cited chunk_indexes.** [82]

**Judge faithfulness.** True — Total net sales figure for 2024 is directly stated in the cited chunk.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-iphone-net-sales`

**Question.** What were Apple's iPhone net sales in fiscal year 2024?

**Expected.** iPhone FY2024 net sales: $201,183M.

**Retrieved top-5 chunk_indexes.** [82, 107, 108, 81, 80]

**Relevant ranks in top-50.** [1, 2]

**Answer.** Apple's iPhone net sales in fiscal year 2024 were $201,183 million

**Cited chunk_indexes.** [82]

**Judge faithfulness.** True — The ANSWER's factual claim is directly supported by the verbatim CITED CHUNKS.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-rd`

**Question.** How much did Apple spend on research and development in fiscal year 2024?

**Expected.** R&D expense FY2024: $31,370M.

**Retrieved top-5 chunk_indexes.** [95, 84, 85, 122, 99]

**Relevant ranks in top-50.** [1, 2]

**Answer.** Apple spent $31,370 million on research and development in fiscal year 2024.

**Cited chunk_indexes.** [95]

**Judge faithfulness.** True — Direct match of R&D expenditure figure in cited chunk.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-iphone16-launch`

**Question.** Which iPhone 16 models did Apple release during fiscal year 2024?

**Expected.** iPhone 16, 16 Plus, 16 Pro, 16 Pro Max.

**Retrieved top-5 chunk_indexes.** [80, 79, 8, 82, 0]

**Relevant ranks in top-50.** [1, 3]

**Answer.** iPhone 16, iPhone 16 Plus, iPhone 16 Pro and iPhone 16 Pro Max

**Cited chunk_indexes.** [80]

**Judge faithfulness.** True — ANSWER is a direct verbatim list from CITED CHUNKS.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-dividend-per-share`

**Question.** What quarterly cash dividend per share did Apple declare during fiscal 2024?

**Expected.** Quarterly dividend: $0.25 per share.

**Retrieved top-5 chunk_indexes.** [88, 99, 95, 79, 109]

**Relevant ranks in top-50.** [1]

**Answer.** The quarterly cash dividend per share was $0.25.

**Cited chunk_indexes.** [88]

**Judge faithfulness.** True — The answer directly quotes a verbatim fact from the cited chunk.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-tax-rate-risk`

**Question.** What risks does Apple identify around changes in its effective tax rate?

**Expected.** Risk factors mention tax-rate changes, new tax legislation, and additional liabilities.

**Retrieved top-5 chunk_indexes.** [67, 68, 59, 124, 85]

**Relevant ranks in top-50.** [1, 2, 5, 18, 19, 29, 35]

**Answer.** Apple identifies risks around changes in its effective tax rate due to changes in tax laws, tax rates, and the mix of earnings in countries with differing statutory tax rates.

**Cited chunk_indexes.** [67, 68]

**Judge faithfulness.** True — ANSWER directly reflects cited risks without addition or paraphrase.

**Human pass/fail.** _TBD — fill in after review._

### `aapl-fy24-argentina-revenue-insufficient`

**Question.** What were Apple's net sales in Argentina in fiscal year 2024?

**Expected.** 10-K breaks geography by Americas/Europe/Greater China/Japan/Rest of Asia Pacific — no country-level Argentina figure.

**Retrieved top-5 chunk_indexes.** [81, 82, 108, 139, 107]

**Relevant ranks in top-50.** []

**Answer.** Insufficient context

**Cited chunk_indexes.** []

**Human pass/fail.** _TBD — fill in after review._

## Theory ↔ Practice

RAGAS (Es 2023) separates retrieval and generation axes. This mini-eval covers retrieval with hit@k / recall@k / MRR / nDCG@k under an approximate keyword ground truth, and generation with a structural citation check plus an LLM-judge faithfulness pass. The single-judge setup inherits bias risks discussed in Zheng 2023; Wave 2 will add a second-judge sanity check and stability across re-runs. ragas itself is intentionally not wired here — it is a Wave-2 dependency choice alongside the bigger 30–50 item set.
