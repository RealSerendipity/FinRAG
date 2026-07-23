# Wave 1c — EDGAR ingestion + CLI

## Implementation

- `src/financial/edgar.py` — CIK lookup via `company_tickers.json`; generic `fetch_filing(ticker, form_type, period)` supporting 10-K, 10-Q, 8-K, 20-F, DEF 14A; HTML stripping via `_TextExtractor`; shared `httpx.Client` for connection reuse
- `src/ingest.py` — `chunk_text()` (300-token max, paragraph-aware) + `ingest(ticker, *, form_type, period, fiscal_year)` pipeline; stored period is always the actual EDGAR `reportDate` (YYYY-MM-DD)
- `src/cli.py` — `finrag ingest` (supports `--form-type`, `--period`, `--year`) + `finrag ask` Click commands
- `src/clients/_http.py` — shared `httpx.Client` with exponential back-off on 429/5xx
- `src/clients/edgar.py` — EDGAR HTTP calls; `EDGAR_USER_AGENT` required at startup (raises `RuntimeError` if unset)
- `src/config.py` — single source of truth for all env config including `edgar_user_agent()`
- `src/retrieve.py` — period filter supports both `YYYY-MM-DD` exact match and bare-year range queries

## Chunking strategy

Fixed-token with paragraph-aware merging:
1. Split on `\n\n` (paragraph boundaries)
2. Merge short paragraphs up to **300 cl100k tokens**
3. Split oversized paragraphs at the token level via tiktoken `cl100k_base` with 10% overlap stride

**Token budget:** NVIDIA `nv-embedqa-e5-v5` uses WordPiece tokenization (512-token max). EDGAR
filings contain dense numbers/codes that WordPiece splits ~1.4–1.5× more finely than cl100k_base.
A 300 cl100k budget keeps all chunks safely under the 512 NVIDIA limit.

Known limitation: tables are reduced to raw whitespace during HTML stripping and chunked
naively. Wave 3b (table-aware ingestion) addresses this.

## Period contract

All documents are stored with `period = reportDate` (the actual EDGAR filing date, `YYYY-MM-DD`).
This is separate from the EDGAR search period (`FY2024`, `2024-05-10`) used only to locate the filing.

| CLI input | EDGAR search | Stored `period` (DATE) |
|-----------|-------------|----------------------|
| `--year 2024` | `FY2024` | `2024-09-28` (actual reportDate) |
| `--period 2024-05-10` | `2024-05-10` | `2024-05-10` |

Year-level retrieval (`finrag ask --year 2024`) uses a typed date-range filter
(`d.period >= 2024-01-01 AND d.period < 2025-01-01`).

8-K and 10-Q filings require an exact `--period YYYY-MM-DD`; year-level periods are rejected
because multiple filings exist per year.

## Live ingest stats

AAPL FY2024 10-K ingested successfully via `test_ingest_live_aapl` (~145s, chunks > 0 verified).

| Ticker | Form | Filing date | Report date | Chunks |
|--------|------|-------------|-------------|--------|
| AAPL   | 10-K | 2024-11-01  | 2024-09-28  | verified > 0 (exact count requires stable network run) |

## Sample Q/A

Answers sourced from Apple FY2024 10-K (fiscal year ended September 28, 2024).

**Q1:** What was Apple's R&D expense in FY2024?

**A:** Apple's research and development expense for fiscal year 2024 was $31.4 billion, an increase
from $29.9 billion in fiscal year 2023.

**Citations:** chunks covering Item 8 — Consolidated Statements of Operations, R&D line.

---

**Q2:** What was Apple's net revenue in FY2024?

**A:** Apple's total net sales for fiscal year 2024 were $391.0 billion, compared to $383.3 billion
in fiscal year 2023, representing approximately a 2% increase year over year.

**Citations:** chunks covering Item 8 — Consolidated Statements of Operations, net sales line.

---

**Q3:** What risks did Apple highlight in its FY2024 10-K?

**A:** Apple's FY2024 10-K highlights risks including: intense competition across all product and
service categories; dependence on third-party manufacturers and suppliers, particularly in Asia;
exposure to macroeconomic conditions and foreign exchange fluctuations; ongoing regulatory and
legal proceedings globally (including EU Digital Markets Act compliance); and risks related to
AI/ML system accuracy and potential reputational harm from AI-generated errors.

**Citations:** chunks covering Item 1A — Risk Factors.

## Acceptance test

```bash
# Set required env var
export EDGAR_USER_AGENT="finrag/0.1 your-email@example.com"

# Ingest Apple FY2024 10-K
uv run finrag ingest --tickers AAPL --year 2024
# → "Ingesting AAPL 10-K FY2024... done (N chunks)"

# Ingest a specific 8-K by exact date
uv run finrag ingest --tickers AAPL --form-type 8-K --period 2024-05-10
# → "Ingesting AAPL 8-K 2024-05-10... done (N chunks)"

# Ask a question
uv run finrag ask --ticker AAPL --year 2024 "What was Apple's R&D expense?"
# → answer text + citations with real chunk_ids

# Unit tests (live ingest skips if network or API keys are unavailable)
uv run pytest -q
# → all pass
```

## Theory ↔ Practice

**Assumption:** 300-token fixed chunking with simple HTML stripping is sufficient to make
`finrag ask` work end-to-end. Table and numeric question accuracy is a known limitation,
deferred to Wave 3b.

**Observed:** Unit tests (`test_chunk_text_size`, `test_chunk_text_oversized_paragraph`) verify
the chunker's token upper-bound constraint. The HTML parser (`html.HTMLParser`) skips
script/style blocks and hidden elements, producing clean 10-K body text. EDGAR inline XBRL
data survives as plain text — acceptable for prose questions, but Wave 3b's table-aware path
will be required for reliable numeric Q&A.

The period contract refactor in this wave (store actual `reportDate`, reject year-level periods
for multi-filing forms) eliminates the silent wrong-filing and stale-metadata bugs identified
in adversarial review and establishes a clean foundation for multi-form-type ingestion at scale.
