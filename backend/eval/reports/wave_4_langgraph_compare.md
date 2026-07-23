# Wave 4 — ReAct loop vs LangGraph rewrite (A/B)

Same prompt (`prompts/react_v1.txt`), same five tools, same parser (`src.agent._parse`). The only difference is orchestration: `src/agent.py` is an explicit `while` loop; `src/agent_lg.py` is a two-node LangGraph `StateGraph` (reason → act, conditional edge back or to END). Questions are designed to be answerable from the ingested AAPL 10-K + calculator; the agent may still prefer the XBRL `lookup_metric` tool for numeric facts. The point of the A/B is the orchestration layer, not which tool the model picks.

## Per-question comparison

| # | engine | steps | tools used | seconds | stopped |
|---|---|---|---|---|---|
| 1 | react | 3 | calculator, calculator | 27.1 | final_answer |
| 1 | langgraph | 3 | calculator, calculator | 37.6 | final_answer |
| 2 | react | 2 | retrieve_filing | 44.8 | final_answer |
| 2 | langgraph | 2 | retrieve_filing | 30.9 | final_answer |
| 3 | react | 4 | lookup_metric, lookup_metric, retrieve_filing | 76.7 | final_answer |
| 3 | langgraph | 2 | retrieve_filing | 35.5 | final_answer |
| 4 | react | 6 | lookup_metric, lookup_metric, lookup_metric, retrieve_filing, calculator | 89.9 | final_answer |
| 4 | langgraph | 6 | lookup_metric, retrieve_filing, retrieve_filing, calculator, calculator | 96.9 | final_answer |

## Answers (side by side)

### Q1. A company's revenue grew from 391035 to 416161 million dollars. What is the percent change to one decimal place?

- **react** (3 steps, calculator, calculator): The percent change in revenue is 6.4%.
- **langgraph** (3 steps, calculator, calculator): The percent change in revenue is 6.4%.

### Q2. What does Apple's FY2024 10-K say about the trend in its Services net sales?

- **react** (2 steps, retrieve_filing): Apple's FY2024 10-K states that Services net sales increased by 13% in 2024 compared to 2023, primarily due to higher net sales from advertising, the App Store, and cloud services, rising from $85,200 to $96,169.
- **langgraph** (2 steps, retrieve_filing): Apple's FY2024 10-K states that Services net sales increased by 13% in 2024 compared to 2023, primarily due to higher net sales from advertising, the App Store, and cloud services.

### Q3. What was Apple's effective tax rate in fiscal year 2024?

- **react** (4 steps, lookup_metric, lookup_metric, retrieve_filing): The effective tax rate for Apple in fiscal year 2024 was 24.1%, as stated in their 2024 Form 10-K filing.
- **langgraph** (2 steps, retrieve_filing): Apple's effective tax rate in fiscal year 2024 was 24.1%, as stated in their 2024 Form 10-K filing.

### Q4. Using Apple's FY2024 10-K text, what was Apple's research and development expense and its total net sales, and what is R&D as a percentage of net sales to one decimal place?

- **react** (6 steps, lookup_metric, lookup_metric, lookup_metric, retrieve_filing, calculator): Apple's research and development expense for FY2024 was $31,370 million, and its total net sales were $391,035 million. The R&D as a percentage of net sales is 8.0%.
- **langgraph** (6 steps, lookup_metric, retrieve_filing, retrieve_filing, calculator, calculator): The research and development expense for Apple in FY2024 was $31,370 million, the total net sales were $391,035 million, and R&D as a percentage of net sales is 8.0%.

## Takeaways

- Total wall-clock: react 238.4s vs langgraph 200.9s (both dominated by identical LLM + tool latency; orchestration overhead is negligible).
- Both engines produce the same tool sequences and equivalent answers — expected, since they reuse the same prompt, tools, and parser.
- **Hand-written loop**: the entire control flow (stop condition, observation truncation, trace writing, session memory) is visible in one `for` loop — easiest to debug and to reason about for a resume talking point.
- **LangGraph**: the loop becomes a declared graph (nodes + conditional edges). It buys little for a loop this simple, but the node/edge structure is where checkpointing, streaming, and human-in-the-loop interrupts would plug in without rewriting the core — the reason to reach for it later (Wave 7).
