# Wave 4 — Agent eval report (engine: react)

- Suite: `eval/agent_questions.jsonl` (18 multi-step tasks, categories: calc, comparison, narrative, numeric, ratio, yoy)
- Tools: retrieve_filing, lookup_metric, compare_companies, web_search, calculator
- Agent: hand-written ReAct loop (`src/agent.py`), max 8 steps, prompt `prompts/react_v1.txt` (sha256 `9c98a37296ec`)
- LLM: `nvidia` / `meta/llama-3.3-70b-instruct`; judge: see Wave 2 config (correctness only)
- SEC reachable this run: 18/18 items (0 network-blocked on the XBRL/web tools)

## Headline metrics

- **task success rate** (all items): 0.94
- **task success rate** (SEC-reachable items only): 0.94
- **tool-call accuracy** (expected tools invoked): 1.00
- **average steps / task**: 3.0
- run errors: 0

Task success = LLM-judge correctness of the final answer vs the expected answer. Tool-call accuracy = fraction of tasks where every tool the task needs was actually invoked. Network-blocked items (SEC XBRL unreachable) are reported separately so an outage is not counted as an agent failure.

## Per-item results

| id | category | steps | tools used | acceptable tools | tool✓ | correct | blocked |
|---|---|---|---|---|---|---|---|
| `aapl-netsales-fy24` | numeric | 2 | lookup_metric | retrieve_filing, lookup_metric | yes | yes |  |
| `aapl-rd-pct-netsales-fy24` | ratio | 4 | lookup_metric, lookup_metric, calculator | retrieve_filing, lookup_metric, calculator (+calc) | yes | yes |  |
| `aapl-netsales-yoy-fy24-fy25` | yoy | 4 | lookup_metric, lookup_metric, calculator | retrieve_filing, lookup_metric, calculator (+calc) | yes | yes |  |
| `aapl-gross-margin-fy24` | ratio | 4 | lookup_metric, lookup_metric, calculator | retrieve_filing, lookup_metric, calculator (+calc) | yes | yes |  |
| `aapl-operating-income-fy24` | numeric | 2 | lookup_metric | retrieve_filing, lookup_metric | yes | yes |  |
| `aapl-rd-yoy-fy24-fy25` | yoy | 4 | lookup_metric, lookup_metric, calculator | retrieve_filing, lookup_metric, calculator (+calc) | yes | yes |  |
| `aapl-services-trend-fy24` | narrative | 2 | retrieve_filing | retrieve_filing | yes | yes |  |
| `aapl-tax-rate-fy24` | numeric | 2 | retrieve_filing | retrieve_filing | yes | yes |  |
| `aapl-net-income-fy24` | numeric | 2 | lookup_metric | retrieve_filing, lookup_metric | yes | yes |  |
| `calc-growth-rate` | calc | 3 | calculator, calculator | calculator (+calc) | yes | yes |  |
| `aapl-sga-fy24` | numeric | 2 | retrieve_filing | retrieve_filing | yes | yes |  |
| `aapl-opex-share-fy24` | ratio | 4 | lookup_metric, lookup_metric, calculator | retrieve_filing, lookup_metric, calculator (+calc) | yes | yes |  |
| `nvda-revenue-fy24-xbrl` | numeric | 2 | lookup_metric | lookup_metric | yes | yes |  |
| `nvda-rd-revenue-ratio-fy24` | ratio | 4 | lookup_metric, lookup_metric, calculator | lookup_metric, calculator (+calc) | yes | yes |  |
| `nvda-vs-amd-revenue-fy24` | comparison | 3 | compare_companies, calculator | compare_companies, lookup_metric, calculator | yes | no |  |
| `msft-net-income-fy24-xbrl` | numeric | 2 | lookup_metric | lookup_metric | yes | yes |  |
| `aapl-rd-fy24-xbrl-crosscheck` | numeric | 2 | lookup_metric | lookup_metric | yes | yes |  |
| `nvda-vs-amd-rd-ratio-fy24` | comparison | 6 | compare_companies, compare_companies, calculator, calculator, calculator | compare_companies, lookup_metric, calculator (+calc) | yes | yes |  |

## Answers + judge reasons

### `aapl-netsales-fy24` (numeric)

**Question.** What were Apple's total net sales for fiscal year 2024? Use the SEC data.

**Expected.** Apple's total net sales for fiscal year 2024 were $391,035 million (about $391.0 billion).

**Answer.** Apple's total net sales for fiscal year 2024 were $391,035 million, according to the net_sales metric from the SEC XBRL filings in their 10-K report for the period ended 2024-09-28.

**Tools.** used=['lookup_metric'] acceptable=['retrieve_filing', 'lookup_metric'] (match=True)

**Judge (primary).** correct=True — ANSWER lacks cited chunks to support its claim.

### `aapl-rd-pct-netsales-fy24` (ratio)

**Question.** What percentage of Apple's total net sales did research and development represent in fiscal 2024? Give the answer to one decimal place.

**Expected.** R&D was $31,370 million on total net sales of $391,035 million, about 8.0% of net sales.

**Answer.** The research and development expenses represented 8.0% of Apple's total net sales in fiscal 2024.

**Tools.** used=['lookup_metric', 'lookup_metric', 'calculator'] acceptable=['retrieve_filing', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — Answer lacks cited chunks to support its claim.

### `aapl-netsales-yoy-fy24-fy25` (yoy)

**Question.** By what percentage did Apple's total net sales change from fiscal 2024 to fiscal 2025? Answer to one decimal place.

**Expected.** Net sales rose from $391,035 million in FY2024 to $416,161 million in FY2025, an increase of about 6.4%.

**Answer.** The total net sales of Apple changed by 6.4% from fiscal 2024 to fiscal 2025.

**Tools.** used=['lookup_metric', 'lookup_metric', 'calculator'] acceptable=['retrieve_filing', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — ANSWER lacks cited chunks to support its claim.

### `aapl-gross-margin-fy24` (ratio)

**Question.** What was Apple's gross margin percentage in fiscal year 2024 (gross profit divided by total net sales)? Answer to one decimal place.

**Expected.** Gross profit was $180,683 million on net sales of $391,035 million, a gross margin of about 46.2%.

**Answer.** Apple's gross margin percentage in fiscal year 2024 was 46.2% (gross profit divided by total net sales).

**Tools.** used=['lookup_metric', 'lookup_metric', 'calculator'] acceptable=['retrieve_filing', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — ANSWER lacks cited chunks to support its claim.

### `aapl-operating-income-fy24` (numeric)

**Question.** What was Apple's operating income in fiscal year 2024?

**Expected.** Apple's operating income in fiscal 2024 was $123,216 million (gross profit $180,683M less total operating expenses $57,467M).

**Answer.** Apple's operating income in fiscal year 2024 was $123,216 million, according to the 10-K filing for the period ended 2024-09-28.

**Tools.** used=['lookup_metric'] acceptable=['retrieve_filing', 'lookup_metric'] (match=True)

**Judge (primary).** correct=True — ANSWER lacks cited chunks to support its claim.

### `aapl-rd-yoy-fy24-fy25` (yoy)

**Question.** By what percentage did Apple's research and development expense grow from fiscal 2024 to fiscal 2025? Answer to one decimal place.

**Expected.** R&D rose from $31,370 million in FY2024 to $34,550 million in FY2025, an increase of about 10.1%.

**Answer.** The research and development expense of Apple grew by 10.1% from fiscal 2024 to fiscal 2025.

**Tools.** used=['lookup_metric', 'lookup_metric', 'calculator'] acceptable=['retrieve_filing', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — No cited chunks provided to support the claim.

### `aapl-services-trend-fy24` (narrative)

**Question.** What does Apple's FY2024 10-K say about the trend in its Services net sales?

**Expected.** Apple's FY2024 10-K states that Services net sales increased during 2024 compared to 2023.

**Answer.** Apple's FY2024 10-K states that Services net sales increased by 13% to $96,169 million in 2024 compared to $85,200 million in 2023, primarily due to higher net sales from advertising, the App Store, and cloud services.

**Tools.** used=['retrieve_filing'] acceptable=['retrieve_filing'] (match=True)

**Judge (primary).** correct=True — ANSWER lacks cited chunks to support its claims.

### `aapl-tax-rate-fy24` (numeric)

**Question.** What was Apple's effective tax rate in fiscal year 2024?

**Expected.** Apple's effective tax rate in fiscal 2024 was 24.1%.

**Answer.** The effective tax rate for Apple in fiscal year 2024 was 24.1%, as stated in the company's 2024 Form 10-K filing.

**Tools.** used=['retrieve_filing'] acceptable=['retrieve_filing'] (match=True)

**Judge (primary).** correct=True — No cited chunks provided to support the claim.

### `aapl-net-income-fy24` (numeric)

**Question.** What was Apple's net income in fiscal year 2024?

**Expected.** Apple's net income in fiscal 2024 was $93,736 million.

**Answer.** Apple's net income in fiscal year 2024 was $93,736 million, according to the 10-K filing for the period ended 2024-09-28.

**Tools.** used=['lookup_metric'] acceptable=['retrieve_filing', 'lookup_metric'] (match=True)

**Judge (primary).** correct=True — No cited chunks provided to support the answer.

### `calc-growth-rate` (calc)

**Question.** If a company's revenue grew from 26,914 million dollars to 60,922 million dollars over two years, what is the total percentage growth? Answer to one decimal place.

**Expected.** The total growth is about 126.4% ((60922-26914)/26914 = 1.264).

**Answer.** The total percentage growth in revenue is 126.4%.

**Tools.** used=['calculator', 'calculator'] acceptable=['calculator'] (match=True)

**Judge (primary).** correct=True — Answer lacks citation but matches expected value.

### `aapl-sga-fy24` (numeric)

**Question.** What were Apple's selling, general and administrative expenses in fiscal 2024?

**Expected.** Apple's selling, general and administrative expense in fiscal 2024 was $26,097 million.

**Answer.** Apple's selling, general and administrative expenses in fiscal 2024 were $26,097 million, as stated in the operating expenses section of the filing.

**Tools.** used=['retrieve_filing'] acceptable=['retrieve_filing'] (match=True)

**Judge (primary).** correct=True — Answer lacks cited chunk support

### `aapl-opex-share-fy24` (ratio)

**Question.** What share of Apple's total operating expenses was research and development in fiscal 2024? Answer to one decimal place.

**Expected.** R&D was $31,370 million of $57,467 million total operating expenses, about 54.6%.

**Answer.** The share of Apple's total operating expenses that was research and development in fiscal 2024 was 54.6%.

**Tools.** used=['lookup_metric', 'lookup_metric', 'calculator'] acceptable=['retrieve_filing', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — Answer lacks cited chunks to support its claim.

### `nvda-revenue-fy24-xbrl` (numeric)

**Question.** What was NVIDIA's total revenue for fiscal year 2024?

**Expected.** NVIDIA's revenue for fiscal 2024 (ended January 28, 2024) was about $60,922 million.

**Answer.** NVIDIA's total revenue for fiscal year 2024 was $60,922 million, according to the 10-K filing.

**Tools.** used=['lookup_metric'] acceptable=['lookup_metric'] (match=True)

**Judge (primary).** correct=True — Answer lacks cited chunks to support its claim.

### `nvda-rd-revenue-ratio-fy24` (ratio)

**Question.** What was NVIDIA's research and development spending as a percentage of revenue in fiscal year 2024? Answer to one decimal place.

**Expected.** NVIDIA's FY2024 R&D was about $8,675 million on revenue of about $60,922 million, roughly 14.2%.

**Answer.** NVIDIA's research and development spending as a percentage of revenue in fiscal year 2024 was 14.2%.

**Tools.** used=['lookup_metric', 'lookup_metric', 'calculator'] acceptable=['lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — Answer matches expected value but lacks cited support.

### `nvda-vs-amd-revenue-fy24` (comparison)

**Question.** Which company had higher total revenue in fiscal year 2024, NVIDIA or AMD, and by approximately how much?

**Expected.** NVIDIA's FY2024 revenue (about $60.9 billion) was substantially higher than AMD's (about $22.7 billion for its fiscal year ended Dec 2023), by roughly $38 billion.

**Answer.** NVIDIA had higher total revenue in fiscal year 2024 than AMD by approximately $35.1 billion, based on the revenue figures from their respective SEC filings.

**Tools.** used=['compare_companies', 'calculator'] acceptable=['compare_companies', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=False — Unsupported claim due to missing cited chunks

### `msft-net-income-fy24-xbrl` (numeric)

**Question.** What was Microsoft's net income for fiscal year 2024?

**Expected.** Microsoft's net income for fiscal 2024 (ended June 30, 2024) was about $88,136 million.

**Answer.** Microsoft's net income for fiscal year 2024 was $88,136 million, according to the 10-K filing for the period ended 2024-06-30.

**Tools.** used=['lookup_metric'] acceptable=['lookup_metric'] (match=True)

**Judge (primary).** correct=True — No cited chunks provided to verify the claim.

### `aapl-rd-fy24-xbrl-crosscheck` (numeric)

**Question.** Using structured SEC financial data, what was Apple's research and development expense in fiscal year 2024?

**Expected.** Apple's FY2024 research and development expense was $31,370 million.

**Answer.** Apple's research and development expense in fiscal year 2024 was $31,370 million, according to the 10-K filing for the period ended 2024-09-28.

**Tools.** used=['lookup_metric'] acceptable=['lookup_metric'] (match=True)

**Judge (primary).** correct=True — No cited chunks provided to verify the claim.

### `nvda-vs-amd-rd-ratio-fy24` (comparison)

**Question.** Compare NVIDIA's and AMD's research-and-development-to-revenue ratios for fiscal year 2024. Which spends a larger share of revenue on R&D?

**Expected.** AMD spends a larger share of revenue on R&D: AMD's R&D/revenue (roughly 25%) exceeds NVIDIA's (roughly 14%) for fiscal 2024.

**Answer.** AMD spends a larger share of its revenue on R&D, with a ratio of approximately 25.04% compared to NVIDIA's 14.24%.

**Tools.** used=['compare_companies', 'compare_companies', 'calculator', 'calculator', 'calculator'] acceptable=['compare_companies', 'lookup_metric', 'calculator'] (match=True)

**Judge (primary).** correct=True — No cited chunks provided to verify factual claims.

## Theory ↔ Practice

ReAct (Yao 2022) interleaves reasoning traces with tool actions; this agent is a hand-written Thought → Action → Observation loop (no framework) so the control flow is fully inspectable and every step is logged to `runs/<id>.jsonl` for replay. The split between retrieve_filing (RAG over prose) and lookup_metric (structured XBRL) follows the rule of thumb that numeric questions should hit structured data, not chunked text. The LangGraph rewrite (`src/agent_lg.py`) expresses the identical loop as a two-node graph; the side-by-side is in `eval/reports/wave_4_langgraph_compare.md`.
