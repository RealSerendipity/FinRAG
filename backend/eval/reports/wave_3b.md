# Wave 3b — Table-aware ingestion (Docling) vs fixed chunking

**Hypothesis.** Serializing tables as independent chunks recovers numeric answers fixed chunking fragments; numeric/table recall@10 rises. If not, Docling's SEC-HTML table extraction is too lossy to help.

- Filings: AAPL FY2024, AAPL FY2025 (10-K raw HTML).
- Table coverage this run: AAPL FY2024 (others' HTML unavailable — EDGAR network-flaky — so those years keep narrative-only chunks)
- Corpus chunk counts: fixed=347, table_aware=454 (fixed narrative + serialized tables).
- Table extraction: Docling HTML backend → compact 'label | value' rows, tables with < 3 numbers dropped.
- Focus set: numeric + table questions (15 items); full set = 36 items. Dense retrieval only.

## numeric + table questions

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| fixed | 0.579 | 0.738 | 0.687 | 0.639 | 0.800 | 0.933 |
| table_aware | 0.493 | 0.671 | 0.730 | 0.610 | 0.733 | 0.933 |

**Headline (numeric+table).** recall@10 0.738 → 0.671 (Δ -0.067); mrr 0.687 → 0.730 (Δ +0.042); recall@5 0.579 → 0.493 (Δ -0.086).

## full question set (regression check)

| variant | recall@5 | recall@10 | mrr | ndcg@10 | hit@5 | hit@10 |
|---|---|---|---|---|---|---|
| fixed | 0.607 | 0.722 | 0.643 | 0.610 | 0.861 | 0.944 |
| table_aware | 0.540 | 0.663 | 0.665 | 0.585 | 0.861 | 0.944 |

## Theory ↔ Practice

A table is a 2-D structure; linearizing a 10-K to text (Wave 1c) destroys the row-label/column-header binding that makes a cell meaningful, so a fixed window can keep '391,035' while losing 'total net sales'. Extracting tables as units and serializing each as 'label | value' rows restores that binding inside a single chunk. The practical limiter is extraction fidelity: SEC HTML nests formatting tables heavily, and an extractor built for clean documents recovers cells unevenly — so the measured delta, not the premise, decides whether table-aware ingestion earns its dependency.
