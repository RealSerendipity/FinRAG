"""SEC EDGAR API client: CIK lookup and 10-K text fetch.

Public surface
--------------
- `cik_for_ticker(ticker)` — returns the integer CIK for a ticker symbol
- `fetch_10k(ticker, year)` — returns {accession, filed_at, raw_url, text} for the 10-K filed in `year`
"""

from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser

import httpx

_HEADERS = {"User-Agent": "finrag/0.1 contact@example.com"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"

_ticker_cik_cache: dict[str, int] | None = None


def _get(url: str) -> bytes:
    resp = httpx.get(url, headers=_HEADERS, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def cik_for_ticker(ticker: str) -> int:
    """Return the integer CIK for a ticker symbol, using a cached company list."""
    global _ticker_cik_cache
    if _ticker_cik_cache is None:
        data = json.loads(_get(_TICKERS_URL))
        _ticker_cik_cache = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    cik = _ticker_cik_cache.get(ticker.upper())
    if cik is None:
        raise ValueError(f"Ticker {ticker!r} not found in EDGAR company list")
    return cik


def fetch_10k(ticker: str, year: int) -> dict:
    """Fetch and return the 10-K filing for `ticker` filed in calendar year `year`.

    Returns a dict with keys: accession, filed_at, raw_url, text.
    Raises ValueError if no matching 10-K is found.
    """
    cik = cik_for_ticker(ticker)
    subs = json.loads(_get(_SUBMISSIONS_URL.format(cik=cik)))

    recent = subs["filings"]["recent"]
    forms: list[str] = recent["form"]
    dates: list[str] = recent["filingDate"]
    accessions: list[str] = recent["accessionNumber"]
    primary_docs: list[str] = recent["primaryDocument"]

    for i, form in enumerate(forms):
        if form != "10-K":
            continue
        if not dates[i].startswith(str(year)):
            continue

        acc = accessions[i]  # e.g. "0000320193-24-000073"
        acc_nodash = acc.replace("-", "")
        doc = primary_docs[i]
        raw_url = _ARCHIVE_URL.format(cik=cik, accession_nodash=acc_nodash, doc=doc)

        time.sleep(0.1)  # EDGAR courtesy rate limit
        raw_bytes = _get(raw_url)
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        text = _strip_html(raw_text)

        return {
            "accession": acc,
            "filed_at": dates[i],
            "raw_url": raw_url,
            "text": text,
        }

    raise ValueError(f"No 10-K found for {ticker!r} filed in {year}")


class _TextExtractor(HTMLParser):
    """Extracts visible text from HTML, skipping script/style blocks."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _strip_html(html: str) -> str:
    """Remove HTML markup and collapse whitespace, returning plain text."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()
