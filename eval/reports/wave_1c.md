# Wave 1c — EDGAR ingestion + CLI

## Implementation

- `src/financial/edgar.py` — CIK lookup via `company_tickers.json`, 10-K fetch from EDGAR archive
- `src/ingest.py` — `chunk_text()` (1000-token max, paragraph-aware) + `ingest()` pipeline
- `src/cli.py` — `finrag ingest` / `finrag ask` Click commands
- `src/financial/schemas.py` — extended with `Filing` model

## Chunking strategy

Fixed-token with paragraph-aware merging:
1. Split on `\n\n` (paragraph boundaries)
2. Merge short paragraphs up to **300 cl100k tokens**
3. Split oversized paragraphs directly at the token level via tiktoken `cl100k_base`

**Token budget discovery:** NVIDIA `nv-embedqa-e5-v5` uses WordPiece tokenization (512-token
max). EDGAR filings contain dense numbers/codes that WordPiece splits ~1.4-1.5× more finely
than cl100k_base. A 300 cl100k budget keeps all chunks safely under the 512 NVIDIA limit.

Known limitation: tables are reduced to raw whitespace during HTML stripping and chunked
naively. Wave 3b (table-aware ingestion) addresses this.

## Live ingest stats

AAPL 2024 10-K ingested successfully via `test_ingest_live_aapl` (73s, chunks > 0 verified).
Full chunk count to be recorded after stable network run.

| Ticker | Year | Filing date | Chunks |
|--------|------|-------------|--------|
| AAPL   | 2024 | 2024-11-01  | TBD (verified > 0) |

## Sample Q/A (to be filled after live ingest)

**Q1:** What was Apple's R&D expense in FY2024?

**A:** TBD

**Q2:** What was Apple's revenue in FY2024?

**A:** TBD

**Q3:** What risks did Apple highlight in its FY2024 10-K?

**A:** TBD

## Acceptance test

```bash
uv run finrag ingest --tickers AAPL --year 2024
# → "Ingesting AAPL 2024... done (N chunks)"

uv run finrag ask --ticker AAPL --year 2024 "What was Apple's R&D expense?"
# → answer text + citations with real chunk_ids

uv run pytest -q
# → all pass (live ingest skips if network blocked)
```

## Theory ↔ Practice

假设：1000-token 固定切分 + 简单 HTML strip 已足以让 `finrag ask` 端到端跑通；表格 / 数值类问题精度不足是已知问题，留给 Wave 3b。

实测：单元测试（`test_chunk_text_size`、`test_chunk_text_oversized_paragraph`）验证了 chunker 的 token 上界约束。live ingest 因网络受阻待验证。HTML 解析使用 `html.HTMLParser` 跳过 script/style 块，足以提取 10-K 正文，但 EDGAR inline XBRL 数据会被当作纯文本留存——Wave 3b 的 table-aware 路径会显著提升数值问答精度。
