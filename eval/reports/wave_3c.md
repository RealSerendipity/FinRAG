# Wave 3c — Hybrid retrieval (pgvector + tsvector RRF)

**Hypothesis.** RRF fusion of dense + lexical lifts recall@10 >= 0.05 on lexical-signal queries vs dense-only; < 0.02 means FTS weighting / fusion needs work.

- Corpus: AAPL 10-Ks (347 chunks); 36 positive eval items.
- `top_k = 10`, RRF k = 60 (Cormack 2009), candidate pool = 50 per ranker; FTS uses OR-semantics tsquery (plainto ANDs, too strict for QA).
- Recall denominator = true count of keyword-relevant chunks in the filtered corpus (comparable across variants).
- Retrieval metrics are LLM-independent — no judge involved.

## Variant comparison (means over positive items)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| dense | 0.607 | 0.722 | 0.643 | 0.610 | 0.861 | 0.944 |
| lexical | 0.410 | 0.655 | 0.489 | 0.461 | 0.722 | 0.833 |
| hybrid | 0.539 | 0.753 | 0.681 | 0.611 | 0.833 | 0.944 |

**Headline.** dense → hybrid: recall@10 0.722 → 0.753 (Δ +0.031); mrr 0.643 → 0.681 (Δ +0.038); ndcg@10 0.610 → 0.611 (Δ +0.001).

## Per-category recall@10

| category | dense | lexical | hybrid |
|---|---|---|---|
| consistency | 0.717 | 0.617 | 0.767 |
| cross-document | 0.656 | 0.531 | 0.667 |
| numeric | 0.557 | 0.445 | 0.521 |
| reasoning | 0.767 | 0.714 | 0.838 |
| table | 0.896 | 0.938 | 0.958 |

## Theory ↔ Practice

Reciprocal Rank Fusion (Cormack 2009) combines rankers by summing 1/(k+rank) without needing comparable score scales — cosine distance and ts_rank_cd are not on the same axis. Dense vectors capture paraphrase/semantic matches; tsvector FTS captures exact tokens (tickers, numeric codes, verbatim phrases). The per-category table shows where lexical signal actually helps versus where semantics already answer the query. On a QA set whose answers (e.g. specific figures) rarely share tokens with the question, lexical contributes little — which is itself the finding, and the reason metadata filtering + reranking carry more of the Wave 3 gains than fusion does on this corpus.
