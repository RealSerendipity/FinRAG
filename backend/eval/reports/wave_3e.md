# Wave 3e — Query rewriting (multi-query / HyDE) on under-specified queries

**Hypothesis.** With the period filter dropped (under-specified), multi-query fusion and/or HyDE lift recall@10 vs a single raw-query dense search; if neither helps, the raw queries already carry enough signal.

- Under-specified condition: ticker filter only, NO period filter (retriever must disambiguate FY2024 vs FY2025 from text alone).
- 36 positive items; `top_k = 10`, multi-query pool = 20/subquery, RRF k = 60.
- Rewrite LLM: NVIDIA NIM (`meta/llama-3.3-70b-instruct`).
- Recall denominator = relevant chunks across the whole-ticker corpus.

## Variant comparison (means over positive items)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| dense (raw) | 0.530 | 0.622 | 0.626 | 0.547 | 0.861 | 0.917 |
| multi-query | 0.506 | 0.606 | 0.654 | 0.544 | 0.889 | 0.889 |
| hyde | 0.483 | 0.676 | 0.588 | 0.512 | 0.944 | 0.972 |

**Headline.** raw → multi-query: recall@10 0.622 → 0.606 (Δ -0.017); raw → HyDE: recall@10 0.622 → 0.676 (Δ +0.054).

## Theory ↔ Practice

Multi-query (RAG-Fusion) hedges against a single bad phrasing by issuing several paraphrases and fusing their rankings with RRF; HyDE (Gao 2022) instead embeds a hypothetical answer, on the bet that an answer-shaped passage sits nearer the real answer chunks in embedding space than the question does. Both trade extra LLM calls (and, for multi-query, extra retrievals) for recall on vague inputs. Dropping the period filter is the honest stress test: with the filter on, metadata already does the disambiguation these rewrites are meant to provide — which is why the shipped default keeps rewriting OFF and relies on metadata + rerank.
