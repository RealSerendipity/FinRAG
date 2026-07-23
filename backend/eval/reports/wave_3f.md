# Wave 3f — Embedding provider comparison (NVIDIA vs Gemini)

**Hypothesis.** Embedding choice shifts recall@10 by more than eval noise (±0.02); if within noise, it is not where Wave 3 effort belongs.

- Corpus: AAPL 10-Ks (347 chunks); 36 positive items; dense (cosine) ranking in numpy.
- NVIDIA `nv-embedqa-e5-v5` (1024-d) vs Gemini `gemini-embedding-001` (3072-d).
- Recall denominator = true count of relevant chunks in the filtered corpus (same for both providers — content is identical).
- Not run: voyage, cohere — API keys absent in this environment.

## Variant comparison (means over positive items)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| nvidia | 0.607 | 0.722 | 0.643 | 0.610 | 0.861 | 0.944 |
| gemini | 0.702 | 0.788 | 0.833 | 0.738 | 0.917 | 0.944 |

| voyage | — | — | — | — | — | — |
| cohere | — | — | — | — | — | — |

**Headline.** NVIDIA → Gemini: recall@10 0.722 → 0.788 (Δ +0.066); mrr 0.643 → 0.833 (Δ +0.190); ndcg@10 0.610 → 0.738 (Δ +0.128).

## Theory ↔ Practice

Embedding models differ in training data, dimensionality, and similarity geometry, so they are not interchangeable — but on a narrow domain a domain-tuned retrieval embedding can match or beat a larger general one. NVIDIA `nv-embedqa-e5-v5` is purpose-built for retrieval QA at 1024-d; Gemini `gemini-embedding-001` is a larger general model at 3072-d (3x the storage and distance-compute cost). The comparison is run with identical chunks and queries so any delta is attributable to the embedding alone; a within-noise result argues for keeping the cheaper, index-matched NVIDIA embedding rather than paying 3x for Gemini vectors.
