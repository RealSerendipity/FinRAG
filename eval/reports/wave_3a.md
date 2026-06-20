# Wave 3a — Chunking strategy (fixed vs sentence-window vs parent-doc)

**Hypothesis.** Sentence-window / parent-doc chunks lift recall@10 over fixed token chunks by keeping narrative answers intact across boundaries; if fixed already wins, the corpus is number/table heavy enough that coherence does not matter.

- Filings: AAPL FY2024, AAPL FY2025 (10-K), dense retrieval only.
- Chunk counts: fixed=347, sentence_window=1889, parent_doc=899.
- Same NVIDIA `nv-embedqa-e5-v5` embeddings; isolated `chunks_ablation` table (production `chunks` untouched).
- 36 positive items; recall denominator per strategy = relevant chunks in that strategy's corpus.

## Variant comparison (means over positive items)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| fixed | 0.607 | 0.722 | 0.643 | 0.610 | 0.861 | 0.944 |
| sentence_window | 0.215 | 0.247 | 0.243 | 0.218 | 0.306 | 0.306 |
| parent_doc | 0.398 | 0.515 | 0.478 | 0.403 | 0.722 | 0.917 |

**Headline.** fixed → sentence_window: recall@10 0.722 → 0.247 (Δ -0.475); mrr 0.643 → 0.243 (Δ -0.400).

## Theory ↔ Practice

Fixed-size chunking is the low ceiling Wave 1c flagged: a token window can cut a sentence — or a number from its label — mid-clause. Sentence-window chunks respect sentence boundaries with overlap so a claim and its context stay together; parent-document chunking goes further, embedding a small precise child for ranking while keeping a larger parent for generation context. Which wins is corpus-dependent: on dense financial tables the child/parent split can fragment a table, so the empirical comparison — not the theory — decides the shipped default.
