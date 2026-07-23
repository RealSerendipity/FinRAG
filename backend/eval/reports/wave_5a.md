# Wave 5A — Public demo (FastAPI + Streamlit)

## What shipped

- `src/api.py` — FastAPI app, four routes verified live over HTTP:
  - `GET /health` → `{"status":"ok","tracing":<bool>}`
  - `POST /ask` → Server-Sent Events: `status` → `answer` → `done` (or `error`)
  - `POST /agent` → JSON: final answer + replayable ReAct steps + tools used
  - `POST /ingest` → JSON: per-ticker chunk counts (idempotent re-ingest)
- `src/ui.py` — Streamlit single-page Q&A over the `/ask` SSE endpoint; each
  citation is a click-to-expand panel with the verbatim quote + chunk id; latency,
  tokens, and `$/query` render under the answer.
- `render.yaml` — two free-tier web services (API + UI) from one repo.

## Hypothesis (first commit)

"Streamlit + FastAPI on Render free tier cold-starts < 30s and p50 query latency
< 8s is the acceptable bar; if it blows past that, streaming (Wave 5B) is needed
before a public demo." Result: **local p50 ≈ 12.6s** on NVIDIA NIM
`llama-3.3-70b` — above the 8s bar, dominated by the hybrid-retrieve + rerank +
70B generation chain, not framework overhead. SSE status events keep the demo
responsive (the client shows "processing" immediately); true token streaming and
prompt caching are the Wave 5B levers.

## Live verification (local, NVIDIA NIM, AAPL FY2024 ingested)

```
GET  /health  → {"status":"ok","tracing":true}   # tracing:false when keys absent
POST /ask     → "Apple's total net sales in fiscal 2024 were $391,035"
                citations=[{chunk_id: 2321, quote: "Total net sales $ 391,035"}]
POST /agent   → "Apple's total net sales in fiscal 2024 were $391,035 million"
                tools_used=["retrieve_filing"], stopped=final_answer
POST /ingest  → {"ticker":"AAPL","chunks":169,"elapsed_s":77.2}
```

`POST /ask` latency sample (5 runs, AAPL FY2024, top_k=5, rerank on):
8.3s · 10.8s · 12.7s · 16.2s · 45.0s → **p50 ≈ 12.6s** (the 45s tail is a cold
NVIDIA reranker/embedding call). Each answer: ~1.7k input + ~50 output tokens,
**$0.00** (open-weight free tier).

## Theory ↔ Practice (LLM Engineer §7 Deploying LLMs)

The deploy chapter frames the demo as "thinnest possible server in front of the
pipeline." Holding to that: the API adds no business logic — it validates input
(pydantic), runs the existing `rag.ask` / `run_agent` in a thread pool so the
event loop stays free, and streams status. The one place reality bit was latency:
a 70B model + reranker makes p50 ≈ 12.6s, so the honest takeaway is that a public
demo wants Wave 5B (streaming + caching), exactly the order the roadmap predicted.
