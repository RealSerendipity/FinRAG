# Wave 3d — Cross-encoder reranking (NVIDIA NeMo Retriever)

**Hypothesis.** Reranking a top-50 pool down to top-10 lifts MRR / nDCG@10 without changing the candidate generator; recall@10 ~flat, recall@5 / MRR up.

- Model: `nvidia/rerank-qa-mistral-4b` via the NeMo Retriever reranking endpoint. The plan named `nv-rerankqa-mistral-4b-v3`, which is not provisioned for this account; the served `rerank-qa-mistral-4b` is used.
- Candidate pool = 50 → reranked to top_k = 10.
- Corpus: AAPL 10-Ks (347 chunks); 36 positive eval items.
- Recall denominator = true count of relevant chunks in the filtered corpus.

## Variant comparison (means over positive items)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| dense | 0.607 | 0.722 | 0.643 | 0.610 | 0.861 | 0.944 |
| dense+rerank | 0.751 | 0.848 | 0.792 | 0.770 | 0.972 | 0.972 |
| hybrid | 0.539 | 0.753 | 0.681 | 0.611 | 0.833 | 0.944 |
| hybrid+rerank | 0.794 | 0.885 | 0.801 | 0.798 | 1.000 | 1.000 |

**Headline.** hybrid → hybrid+rerank: mrr 0.681 → 0.801 (Δ +0.120); ndcg@10 0.611 → 0.798 (Δ +0.187); recall@5 0.539 → 0.794 (Δ +0.254).

## Theory ↔ Practice

A bi-encoder (the embedding model) encodes query and passage separately, so it cannot model token-level interaction; a cross-encoder reranker reads the (query, passage) pair jointly and scores relevance directly. The cost is latency, so the standard pattern is retrieve-cheap-then-rerank: pull a wide candidate pool with the bi-encoder/RRF, then spend the cross-encoder only on those candidates. A good reranker's signature is rank quality up (MRR / nDCG / recall@5) with recall@10 roughly preserved, since it reorders rather than expands the candidate set.
