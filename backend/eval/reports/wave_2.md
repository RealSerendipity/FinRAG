# Wave 2 — Eval harness report (Wave 1 baseline)

- Corpus: AAPL FY2024 10-K (`0000320193-24-000123`) + AAPL FY2025 10-K (`0000320193-25-000079`)
- Items: 38 (36 positive + 2 insufficient-context), 5 categories
- `answer top_k = 5`, probe `K_max = 50`
- LLM provider: `nvidia` / model: `meta/llama-3.3-70b-instruct`
- Judge provider: `nvidia` / model: `nvidia/llama-3.3-nemotron-super-49b-v1` (fallback: `gemini/gemini-2.5-flash-lite`)
- Prompt: `prompts/answer_v1.1.txt` (sha256 `8c1f37f68d09`)
- Embedding: NVIDIA NeMo Retriever `nv-embedqa-e5-v5`

## Headline metrics (means over positive items unless noted)

- **recall@5**: 0.66
- **recall@10**: 0.80
- **MRR**: 0.64
- **nDCG@10**: 0.65
- **doc coverage@10**: 1.00
- **citation validity** (all items, structural): 0.82
- **faithfulness** (judged 31/36): 0.84
- **answer relevancy**: 0.94
- **correctness vs expected answer**: 0.84

Relevance ground truth is OR-of-AND keyword groups (Wave 1.5 convention), so recall/nDCG use a local denominator (relevants found within top-50). Doc coverage@10 is the fraction of expected filings present among the top-10 retrieved chunks' documents.

## Per-category breakdown

| category | n | hit@5 | recall@10 | MRR | nDCG@10 | cite valid | faithful | relevant | correct |
|---|---|---|---|---|---|---|---|---|---|
| numeric | 8 | 0.57 | 0.71 | 0.40 | 0.47 | 0.62 | 1.00 | 1.00 | 1.00 |
| table | 8 | 1.00 | 0.90 | 0.94 | 0.86 | 1.00 | 1.00 | 1.00 | 1.00 |
| cross-document | 8 | 0.88 | 0.79 | 0.62 | 0.62 | 0.75 | 0.57 | 0.86 | 0.57 |
| reasoning | 7 | 1.00 | 0.83 | 0.74 | 0.71 | 1.00 | 0.86 | 1.00 | 0.86 |
| consistency | 7 | 0.83 | 0.72 | 0.45 | 0.52 | 0.71 | 0.80 | 0.80 | 0.80 |

## Consistency pairs (paraphrase vs base phrasing)

| paraphrase | base | paraphrase correct | base correct | agree |
|---|---|---|---|---|
| `cons-fy24-revenue-paraphrase` | `aapl-fy24-total-net-sales` | yes | yes | yes |
| `cons-fy25-rd-paraphrase` | `aapl-fy25-rd-expense` | — | — | — |
| `cons-fy24-eps-paraphrase` | `aapl-fy24-diluted-eps` | yes | yes | yes |
| `cons-fy25-iphone-paraphrase` | `aapl-fy25-iphone-net-sales` | no | yes | no |
| `cons-fy25-tax-rate-paraphrase` | `aapl-fy25-effective-tax-rate` | yes | yes | yes |
| `cons-fy24-gross-margin-paraphrase` | `aapl-fy24-gross-margin-pct` | yes | yes | yes |

## Per-item results

| id | cat | hit@5 | recall@10 | MRR | nDCG@10 | cite | faithful | correct | rel in probe |
|---|---|---|---|---|---|---|---|---|---|
| `aapl-fy24-total-net-sales` | numeric | yes | 1.00 | 1.00 | 0.92 | yes | yes | yes | 5 |
| `aapl-fy25-total-net-sales` | numeric | yes | 0.67 | 1.00 | 0.74 | yes | yes | yes | 6 |
| `aapl-fy24-rd-expense` | numeric | yes | 0.50 | 0.33 | 0.31 | yes | yes | yes | 2 |
| `aapl-fy25-rd-expense` | numeric | no | — | 0.00 | — | no | — | — | 0 |
| `aapl-fy24-net-income` | numeric | yes | 0.67 | 0.20 | 0.32 | yes | yes | yes | 3 |
| `aapl-fy25-net-income` | numeric | no | 0.40 | 0.17 | 0.22 | no | — | — | 5 |
| `aapl-fy25-cash-and-securities` | numeric | no | 1.00 | 0.11 | 0.30 | no | — | — | 1 |
| `aapl-fy24-watch-revenue-insufficient` | numeric | — | — | — | — | yes | — | — | 0 |
| `aapl-fy24-iphone-net-sales` | table | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 2 |
| `aapl-fy25-iphone-net-sales` | table | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 2 |
| `aapl-fy24-services-net-sales` | table | yes | 0.67 | 1.00 | 0.70 | yes | yes | yes | 3 |
| `aapl-fy25-mac-net-sales` | table | yes | 1.00 | 0.50 | 0.65 | yes | yes | yes | 2 |
| `aapl-fy24-gross-margin-pct` | table | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 1 |
| `aapl-fy25-effective-tax-rate` | table | yes | 0.50 | 1.00 | 0.61 | yes | yes | yes | 2 |
| `aapl-fy24-diluted-eps` | table | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 2 |
| `aapl-fy25-greater-china-net-sales` | table | yes | 1.00 | 1.00 | 0.93 | yes | yes | yes | 3 |
| `xdoc-iphone-yoy` | cross-document | yes | 1.00 | 1.00 | 0.93 | yes | yes | yes | 4 |
| `xdoc-rd-trend` | cross-document | no | 0.67 | 0.17 | 0.32 | no | no | no | 3 |
| `xdoc-services-growth` | cross-document | yes | 0.67 | 0.50 | 0.56 | yes | yes | yes | 6 |
| `xdoc-tax-rate-change` | cross-document | yes | 0.50 | 1.00 | 0.64 | yes | no | no | 4 |
| `xdoc-dividend-change` | cross-document | yes | 0.50 | 0.50 | 0.39 | yes | no | no | 2 |
| `xdoc-buyback-programs` | cross-document | yes | 1.00 | 0.50 | 0.74 | yes | yes | yes | 4 |
| `xdoc-employees-change` | cross-document | yes | 1.00 | 0.33 | 0.50 | no | — | — | 1 |
| `xdoc-deferred-revenue-change` | cross-document | yes | 1.00 | 1.00 | 0.92 | yes | yes | yes | 2 |
| `reas-fy24-tax-rate-why` | reasoning | yes | 0.50 | 1.00 | 0.61 | yes | yes | yes | 2 |
| `reas-fy25-products-gm-why` | reasoning | yes | 1.00 | 0.50 | 0.63 | yes | yes | yes | 1 |
| `reas-seasonality` | reasoning | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 2 |
| `reas-fy25-us-tariffs` | reasoning | yes | 1.00 | 0.33 | 0.50 | yes | no | no | 2 |
| `reas-fy24-state-aid-obligation` | reasoning | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 1 |
| `reas-fy25-iphone-growth-driver` | reasoning | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 1 |
| `reas-supply-chain-concentration` | reasoning | yes | 0.33 | 0.33 | 0.23 | yes | yes | yes | 3 |
| `cons-fy24-revenue-paraphrase` | consistency | yes | 0.80 | 0.33 | 0.53 | yes | yes | yes | 5 |
| `cons-fy25-rd-paraphrase` | consistency | no | 0.00 | 0.03 | 0.00 | no | — | — | 1 |
| `cons-fy24-eps-paraphrase` | consistency | yes | 1.00 | 1.00 | 1.00 | yes | yes | yes | 2 |
| `cons-fy25-iphone-paraphrase` | consistency | yes | 1.00 | 0.33 | 0.57 | no | no | no | 2 |
| `cons-fy25-tax-rate-paraphrase` | consistency | yes | 0.50 | 0.50 | 0.39 | yes | yes | yes | 2 |
| `cons-fy24-gross-margin-paraphrase` | consistency | yes | 1.00 | 0.50 | 0.63 | yes | yes | yes | 1 |
| `cons-fy25-argentina-insufficient` | consistency | — | — | — | — | yes | — | — | 0 |

## Answers + judge reasons

### `aapl-fy24-total-net-sales` (numeric)

**Question.** What were Apple's total net sales for fiscal year 2024?

**Expected.** Apple's total net sales for fiscal year 2024 were $391,035 million (about $391.0 billion), up 2% year over year.

**Answer.** Apple's total net sales for fiscal year 2024 were $391,035 million

**Cited chunk_ids.** [2126]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with direct citation.

### `aapl-fy25-total-net-sales` (numeric)

**Question.** What were Apple's total net sales for fiscal year 2025?

**Expected.** Apple's total net sales for fiscal year 2025 were $416,161 million (about $416.2 billion), up 6% year over year.

**Answer.** Apple's total net sales for fiscal year 2025 were $416,161

**Cited chunk_ids.** [286]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER directly quotes the total net sales figure from the cited chunk.

### `aapl-fy24-rd-expense` (numeric)

**Question.** How much did Apple spend on research and development in fiscal year 2024?

**Expected.** Apple's research and development expense in fiscal year 2024 was $31,370 million, about 8% of total net sales.

**Answer.** Apple spent $31,370 on research and development in fiscal year 2024.

**Cited chunk_ids.** [2139]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with cited chunk support.

### `aapl-fy25-rd-expense` (numeric)

**Question.** How much did Apple spend on research and development in fiscal year 2025?

**Expected.** Apple's research and development expense in fiscal year 2025 was $34,550 million, up 10% from fiscal 2024.

**Answer.** Insufficient context

**Cited chunk_ids.** []

### `aapl-fy24-net-income` (numeric)

**Question.** What was Apple's net income in fiscal year 2024?

**Expected.** Apple's net income for fiscal year 2024 was $93,736 million.

**Answer.** Apple's net income in fiscal year 2024 was $93,736

**Cited chunk_ids.** [2139]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with direct citation.

### `aapl-fy25-net-income` (numeric)

**Question.** What was Apple's net income in fiscal year 2025?

**Expected.** Apple's net income for fiscal year 2025 was $112,010 million.

**Answer.** Insufficient context

**Cited chunk_ids.** []

### `aapl-fy25-cash-and-securities` (numeric)

**Question.** What was the total of Apple's cash, cash equivalents and marketable securities as of the end of fiscal year 2025?

**Expected.** Apple's cash, cash equivalents and marketable securities totaled $132.4 billion as of September 27, 2025.

**Answer.** Insufficient context

**Cited chunk_ids.** []

### `aapl-fy24-watch-revenue-insufficient` (numeric)

**Question.** What were Apple's net sales for the Apple Watch product line alone in fiscal year 2024?

**Expected.** Insufficient context

**Answer.** Insufficient context

**Cited chunk_ids.** []

### `aapl-fy24-iphone-net-sales` (table)

**Question.** What were Apple's iPhone net sales in fiscal year 2024?

**Expected.** iPhone net sales in fiscal year 2024 were $201,183 million, roughly flat year over year.

**Answer.** Apple's iPhone net sales in fiscal year 2024 were $201,183 million

**Cited chunk_ids.** [2126]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value and cites direct evidence.

### `aapl-fy25-iphone-net-sales` (table)

**Question.** What were Apple's iPhone net sales in fiscal year 2025?

**Expected.** iPhone net sales in fiscal year 2025 were $209,586 million, up 4% year over year.

**Answer.** Apple's iPhone net sales in fiscal year 2025 were $209,586

**Cited chunk_ids.** [259]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value and cites direct source.

### `aapl-fy24-services-net-sales` (table)

**Question.** What were Apple's Services net sales in fiscal year 2024?

**Expected.** Services net sales in fiscal year 2024 were $96,169 million, up 13% year over year.

**Answer.** Apple's Services net sales in fiscal year 2024 were $96,169 million

**Cited chunk_ids.** [2126]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with direct citation.

### `aapl-fy25-mac-net-sales` (table)

**Question.** What were Apple's Mac net sales in fiscal year 2025?

**Expected.** Mac net sales in fiscal year 2025 were $33,708 million, up 12% year over year.

**Answer.** Apple's Mac net sales in fiscal year 2025 were $33,708 million

**Cited chunk_ids.** [259]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with direct citation.

### `aapl-fy24-gross-margin-pct` (table)

**Question.** What was Apple's total gross margin percentage in fiscal year 2024?

**Expected.** Apple's total gross margin percentage in fiscal year 2024 was 46.2% (total gross margin of $180,683 million).

**Answer.** 46.2%

**Cited chunk_ids.** [2127]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value and is directly supported by cited chunk.

### `aapl-fy25-effective-tax-rate` (table)

**Question.** What was Apple's effective tax rate in fiscal year 2025?

**Expected.** Apple's effective tax rate in fiscal year 2025 was 15.6%.

**Answer.** 15.6%

**Cited chunk_ids.** [262]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value and is directly supported by cited chunk.

### `aapl-fy24-diluted-eps` (table)

**Question.** What was Apple's diluted earnings per share in fiscal year 2024?

**Expected.** Apple's diluted earnings per share in fiscal year 2024 was $6.08.

**Answer.** Apple's diluted earnings per share in fiscal year 2024 was $6.08

**Cited chunk_ids.** [2153]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value and is directly supported by cited chunk.

### `aapl-fy25-greater-china-net-sales` (table)

**Question.** What were Apple's Greater China net sales in fiscal year 2025?

**Expected.** Greater China net sales in fiscal year 2025 were $64,377 million, down 4% year over year.

**Answer.** Apple's Greater China net sales in fiscal year 2025 were $64,377 million

**Cited chunk_ids.** [319, 258]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER matches EXPECTED value and cites supporting chunk.

### `xdoc-iphone-yoy` (cross-document)

**Question.** How did Apple's iPhone net sales change from fiscal year 2024 to fiscal year 2025?

**Expected.** iPhone net sales grew from $201,183 million in fiscal 2024 to $209,586 million in fiscal 2025, an increase of about 4%, driven by higher net sales of Pro models.

**Answer.** iPhone net sales increased by 4%

**Cited chunk_ids.** [259]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer's 4% increase matches expected and is supported by cited chunk.

### `xdoc-rd-trend` (cross-document)

**Question.** How has Apple's research and development expense evolved from fiscal year 2023 through fiscal year 2025?

**Expected.** R&D expense rose from $29,915 million in fiscal 2023 to $31,370 million in fiscal 2024 (up 5%) and to $34,550 million in fiscal 2025 (up 10%).

**Answer.** The growth in R&D expense during 2025 compared to 2024 was primarily driven by increases in headcount-related expenses and infrastructure-related costs.

**Cited chunk_ids.** [262]

**Judge (primary).** faithful=no, relevant=no, correct=no — Answer discusses drivers of 2025 R&D growth but doesn't provide the evolution of R&D expenses across the specified years.

### `xdoc-services-growth` (cross-document)

**Question.** How did Apple's Services net sales change between fiscal year 2024 and fiscal year 2025?

**Expected.** Services net sales grew from $96,169 million in fiscal 2024 to $109,158 million in fiscal 2025, an increase of about 14%.

**Answer.** Apple's Services net sales increased by 14% between fiscal year 2024 and fiscal year 2025.

**Cited chunk_ids.** [259]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER matches EXPECTED's primary fact (14% increase) and is supported by CITED CHUNKS.

### `xdoc-tax-rate-change` (cross-document)

**Question.** How did Apple's effective tax rate change from fiscal year 2024 to fiscal year 2025, and why?

**Expected.** The effective tax rate fell from 24.1% in fiscal 2024 to 15.6% in fiscal 2025, mainly because fiscal 2024 included a one-time income tax charge of $10.2 billion, net, related to the State Aid Decision.

**Answer.** Apple's effective tax rate decreased from 24.1% in 2024 to 15.6% in 2025. The decrease was primarily due to a lower effective tax rate on foreign earnings and the impact of changes in unrecognized tax benefits.

**Cited chunk_ids.** [262, 263]

**Judge (primary).** faithful=no, relevant=yes, correct=no — Incorrect reason for tax rate change, unsupported by cited chunks

### `xdoc-dividend-change` (cross-document)

**Question.** How did Apple's quarterly cash dividend per share change between fiscal year 2024 and fiscal year 2025?

**Expected.** Apple raised its quarterly dividend from $0.24 to $0.25 per share beginning in May 2024, and from $0.25 to $0.26 per share beginning in May 2025.

**Answer.** The quarterly cash dividend per share increased from $0.25 to $0.26

**Cited chunk_ids.** [265]

**Judge (primary).** faithful=no, relevant=yes, correct=no — Missing 2024 dividend value and change detail

### `xdoc-buyback-programs` (cross-document)

**Question.** What share repurchase programs did Apple announce in fiscal years 2024 and 2025, and how much stock did it actually repurchase in each year?

**Expected.** In May 2024 Apple announced a share repurchase program of up to $110 billion and repurchased $95.0 billion of its stock during fiscal 2024; in May 2025 it announced a new program of up to $100 billion and repurchased $89.3 billion during fiscal 2025.

**Answer.** Apple announced a $110 billion share repurchase program in May 2024 and a $100 billion program in May 2025. It repurchased $95.0 billion of stock in 2024 and $89.3 billion in 2025.

**Cited chunk_ids.** [252, 252, 2175, 310]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected values for program announcements and actual repurchases in both years, fully supported by cited chunks.

### `xdoc-employees-change` (cross-document)

**Question.** How did Apple's number of full-time equivalent employees change between the end of fiscal 2024 and the end of fiscal 2025?

**Expected.** Apple had approximately 164,000 full-time equivalent employees as of September 28, 2024 and approximately 166,000 as of September 27, 2025.

**Answer.** Insufficient context

**Cited chunk_ids.** []

### `xdoc-deferred-revenue-change` (cross-document)

**Question.** How did Apple's total deferred revenue change from the end of fiscal 2024 to the end of fiscal 2025?

**Expected.** Total deferred revenue was $12.8 billion as of September 28, 2024 and grew to $13.7 billion as of September 27, 2025.

**Answer.** Apple's total deferred revenue increased from $12.8 billion to $13.7 billion

**Cited chunk_ids.** [287]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer directly matches expected values with cited support.

### `reas-fy24-tax-rate-why` (reasoning)

**Question.** Why was Apple's fiscal 2024 effective tax rate higher than the U.S. statutory federal income tax rate?

**Expected.** Primarily because of a one-time income tax charge of $10.2 billion, net, related to the State Aid Decision, plus state income taxes, partially offset by a lower effective tax rate on foreign earnings, the U.S. federal R&D credit, and tax benefits from share-based compensation.

**Answer.** Apple's fiscal 2024 effective tax rate was higher than the U.S. statutory federal income tax rate due to a one-time income tax charge and state income taxes.

**Cited chunk_ids.** [2129]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER accurately reflects the primary reasons stated in CITED CHUNKS, omitting only secondary offsetting factors mentioned in EXPECTED.

### `reas-fy25-products-gm-why` (reasoning)

**Question.** Why did Apple's Products gross margin percentage decrease in fiscal year 2025?

**Expected.** Products gross margin percentage decreased primarily due to a different mix of products and tariff costs, partially offset by other favorable costs.

**Answer.** Apple's Products gross margin percentage decreased in fiscal year 2025 primarily due to a different mix of products and tariff costs, partially offset by other favorable costs.

**Cited chunk_ids.** [261]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER matches EXPECTED and is directly supported by CITED CHUNKS.

### `reas-seasonality` (reasoning)

**Question.** Why does Apple historically report higher net sales in its first fiscal quarter?

**Expected.** Because of seasonal holiday demand: Apple has historically experienced higher net sales in its first quarter compared to other quarters, due in part to seasonal holiday demand.

**Answer.** Due to seasonal holiday demand

**Cited chunk_ids.** [2107]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER directly quotes the cited chunk's reason for higher Q1 sales.

### `reas-fy25-us-tariffs` (reasoning)

**Question.** What new tariff developments did Apple describe in its fiscal 2025 10-K, and what risks do they pose?

**Expected.** Beginning in the second quarter of 2025, new U.S. tariffs were announced on imports to the U.S., including additional tariffs on imports from China, India, Japan, South Korea, Taiwan, Vietnam and the EU; several countries imposed or threatened reciprocal tariffs. These restrictions can raise costs, limit product availability, force supply-chain changes and hurt results.

**Answer.** New tariffs were announced on imports to the U.S., including additional tariffs on imports from China, India, Japan, South Korea, Taiwan, Vietnam and the EU. These tariffs pose risks of significant disruptions to global supply chains, shifts and reductions in consumer spending, and negative consumer sentiment for the Company's products and services.

**Cited chunk_ids.** [195, 195]

**Judge (primary).** faithful=no, relevant=yes, correct=no — Added unsupported risks and omitted specific timing and reciprocal tariffs.

### `reas-fy24-state-aid-obligation` (reasoning)

**Question.** What obligation did Apple have to Ireland as of the end of fiscal 2024 in connection with the State Aid Decision?

**Expected.** As of September 28, 2024, Apple had an obligation to pay €14.2 billion ($15.8 billion) to Ireland in connection with the State Aid Decision, expected to be paid within 12 months, with the funds held in escrow and restricted from general use.

**Answer.** Apple had an obligation to pay €14.2 billion or $15.8 billion to Ireland

**Cited chunk_ids.** [2132]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER matches EXPECTED's primary fact with direct citation support.

### `reas-fy25-iphone-growth-driver` (reasoning)

**Question.** What drove the growth in Apple's iPhone net sales during fiscal year 2025?

**Expected.** iPhone net sales increased during fiscal 2025 due to higher net sales of Pro models.

**Answer.** Higher net sales of Pro models

**Cited chunk_ids.** [259]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer directly matches expected and is supported by cited chunk.

### `reas-supply-chain-concentration` (reasoning)

**Question.** Where is the majority of Apple's manufacturing performed, according to its 10-K risk disclosures?

**Expected.** A significant majority of Apple's manufacturing is performed in whole or in part by outsourcing partners located primarily in China mainland, India, Japan, South Korea, Taiwan and Vietnam, in addition to U.S. partners and facilities.

**Answer.** China mainland, India, Japan, South Korea, Taiwan and Vietnam

**Cited chunk_ids.** [315]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — ANSWER directly quotes the primary locations from CITED CHUNKS, matching EXPECTED.

### `cons-fy24-revenue-paraphrase` (consistency)

**Question.** How much revenue did Apple generate in fiscal 2024?

**Expected.** Apple generated total net sales of $391,035 million (about $391.0 billion) in fiscal year 2024.

**Answer.** Apple generated $391,035 million in revenue in fiscal 2024

**Cited chunk_ids.** [2151]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with direct citation.

### `cons-fy25-rd-paraphrase` (consistency)

**Question.** What was Apple's R&D budget actually spent in fiscal 2025?

**Expected.** Apple spent $34,550 million on research and development in fiscal year 2025.

**Answer.** Insufficient context

**Cited chunk_ids.** []

### `cons-fy24-eps-paraphrase` (consistency)

**Question.** How much did Apple earn per diluted share in fiscal year 2024?

**Expected.** Apple earned $6.08 per diluted share in fiscal year 2024.

**Answer.** Apple earned $6.08 per diluted share in fiscal year 2024

**Cited chunk_ids.** [2153]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value with direct support from cited chunk.

### `cons-fy25-iphone-paraphrase` (consistency)

**Question.** How much revenue did the iPhone business bring in during Apple's fiscal 2025?

**Expected.** The iPhone business generated net sales of $209,586 million in fiscal year 2025.

**Answer.** $209,586

**Cited chunk_ids.** [262]

**Judge (primary).** faithful=no, relevant=no, correct=no — ANSWER lacks supporting evidence in CITED CHUNKS

### `cons-fy25-tax-rate-paraphrase` (consistency)

**Question.** What proportion of its pre-tax income did Apple record as income tax provision in fiscal 2025, i.e. its effective tax rate?

**Expected.** Apple's effective tax rate for fiscal year 2025 was 15.6%.

**Answer.** 15.6%

**Cited chunk_ids.** [262]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer matches expected value and is directly supported by cited chunk.

### `cons-fy24-gross-margin-paraphrase` (consistency)

**Question.** What share of Apple's fiscal 2024 net sales was left as gross profit?

**Expected.** Apple's total gross margin percentage was 46.2% of net sales in fiscal year 2024.

**Answer.** 46.2%

**Cited chunk_ids.** [2127]

**Judge (primary).** faithful=yes, relevant=yes, correct=yes — Answer directly matches the total gross margin percentage stated in the cited chunk.

### `cons-fy25-argentina-insufficient` (consistency)

**Question.** What were Apple's net sales in Argentina in fiscal year 2025?

**Expected.** Insufficient context

**Answer.** Insufficient context

**Cited chunk_ids.** []

## Stability

_Run this harness twice; headline numbers should agree within ±0.02 (acceptance gate). Fill in after the rerun:_

| metric | run 1 | run 2 | |Δ| |
|---|---|---|---|

## Theory ↔ Practice

RAGAS (Es 2023) separates retrieval and generation quality; this harness measures retrieval with recall@k / MRR / nDCG over a keyword ground truth and generation with a structural citation check plus an LLM judge for faithfulness, answer relevancy, and correctness. Following Zheng 2023 on judge bias, the judge is a different provider than the generator, runs at temperature 0 with a binary rubric, and the cheap-fallback path reflects the observation that inexpensive judges suffice for *relative* comparisons between retrieval variants — the use this harness is built for (Wave 3 ablations).
