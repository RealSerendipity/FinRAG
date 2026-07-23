# Wave 3g — Section/layout-aware chunking + heading prefix vs fixed

**Hypothesis.** Splitting at 10-K structural headings (Item / Part) and prefixing each chunk with its section heading lifts recall@10 / MRR vs fixed token chunking.

- Filings: AAPL FY2024, AAPL FY2025 (10-K), dense only.
- Chunk counts: fixed=347, section=428.
- Same NVIDIA `nv-embedqa-e5-v5` embeddings; isolated `chunks_ablation` table.
- 36 positive items; recall denominator per strategy = relevant chunks in that strategy's corpus.

## Variant comparison (means over positive items)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| fixed | 0.607 | 0.722 | 0.643 | 0.610 | 0.861 | 0.944 |
| section | 0.447 | 0.590 | 0.567 | 0.466 | 0.806 | 0.861 |

**Headline.** fixed → section: recall@10 0.722 → 0.590 (Δ -0.131); mrr 0.643 → 0.567 (Δ -0.076); ndcg@10 0.610 → 0.466 (Δ -0.143).

## Theory ↔ Practice

10-K structure is strong and regular (Item 1 Business, 1A Risk Factors, 7 MD&A, 8 Financial Statements), so section boundaries are a reliable place to cut, and prefixing the section heading injects context the bi-encoder would otherwise miss. Both are near-free at ingest.

**Verdict: rejected — keep `fixed`.** Section-aware lost on every metric (recall@10 −0.131, MRR −0.076, nDCG −0.143). This is the same mechanism Wave 3a found for sentence-window / parent-doc: on a small, number/table-dense corpus measured by keyword recall, finer chunking (428 vs 347 chunks) spreads the answer token across more chunks and inflates the recall denominator, so the answer-bearing chunk ranks lower. The heading prefix also repeats near-identical boilerplate across a section's chunks, reducing embedding discriminability. Chunking is effectively exhausted as a lever on this corpus — every alternative to `fixed` (3a + 3g) underperforms it. The real Wave 3 gains were query-time (hybrid + rerank), and numeric accuracy is better pursued via structured XBRL / text-to-SQL (Wave 7.sql) than via more chunking. Heading-context's potential upside is in *generation* faithfulness, not retrieval — not worth a slow run_eval given the clear retrieval regression.
