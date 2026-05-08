"""SEC EDGAR API client: CIK lookup and 10-K text fetch.

Public surface
--------------
- `cik_for_ticker(ticker)` — returns the integer CIK for a ticker symbol
- `fetch_10k(ticker, fiscal_year)` — returns {accession, filed_at, report_date, raw_url, text}
  for the 10-K whose period-of-report falls in `fiscal_year`
"""

from __future__ import annotations

import json
import os
import re
import time
from html.parser import HTMLParser

import httpx

# EDGAR requires a real company/contact User-Agent.  Override via EDGAR_USER_AGENT env var.
_USER_AGENT = os.getenv("EDGAR_USER_AGENT", "finrag/0.1 finrag-user@example.com")
_HEADERS = {"User-Agent": _USER_AGENT}

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_SUBMISSIONS_EXTRA_URL = "https://data.sec.gov/submissions/{name}"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"

_ticker_cik_cache: dict[str, int] | None = None

_BLOCK_TAGS = frozenset(
    "p div h1 h2 h3 h4 h5 h6 li tr td th section article header footer "
    "blockquote pre ul ol dl dt dd table caption".split()
)
_SELF_CLOSE_TAGS = frozenset(["br", "hr"])


def _get(url: str, *, retries: int = 3) -> bytes:
    """Fetch URL with simple exponential back-off on 429 / 5xx."""
    delay = 1.0
    for attempt in range(retries):
        resp = httpx.get(url, headers=_HEADERS, timeout=60, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
        resp.raise_for_status()
        return resp.content
    resp.raise_for_status()  # raise on final attempt
    return resp.content  # unreachable but satisfies type checker


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


def _iter_filing_pages(subs: dict) -> list[dict]:
    """Yield the recent filings dict, then any paginated historical filing pages."""
    pages = [subs["filings"]["recent"]]
    for extra in subs["filings"].get("files", []):
        extra_url = _SUBMISSIONS_EXTRA_URL.format(name=extra["name"])
        extra_data = json.loads(_get(extra_url))
        pages.append(extra_data)
    return pages


def fetch_10k(ticker: str, fiscal_year: int) -> dict:
    """Fetch the 10-K whose period-of-report (reportDate) falls in `fiscal_year`.

    Returns a dict with keys: accession, filed_at, report_date, raw_url, text.
    Raises ValueError if no matching 10-K is found.
    """
    cik = cik_for_ticker(ticker)
    subs = json.loads(_get(_SUBMISSIONS_URL.format(cik=cik)))

    for page in _iter_filing_pages(subs):
        forms: list[str] = page["form"]
        filing_dates: list[str] = page["filingDate"]
        report_dates: list[str] = page.get("reportDate", [""] * len(forms))
        accessions: list[str] = page["accessionNumber"]
        primary_docs: list[str] = page["primaryDocument"]

        for i, form in enumerate(forms):
            if form != "10-K":
                continue
            # Use reportDate (period-of-report) to match fiscal year, not filingDate.
            rdate = report_dates[i] if i < len(report_dates) else ""
            if not rdate or not rdate.startswith(str(fiscal_year)):
                continue

            acc = accessions[i]  # e.g. "0000320193-24-000073"
            acc_nodash = acc.replace("-", "")
            doc = primary_docs[i]
            raw_url = _ARCHIVE_URL.format(cik=cik, accession_nodash=acc_nodash, doc=doc)

            time.sleep(0.1)  # EDGAR courtesy rate limit
            raw_bytes = _get(raw_url)
            # Use httpx-detected encoding, fall back to latin-1 (common for older SEC filings).
            encoding = _detect_encoding(raw_bytes)
            raw_text = raw_bytes.decode(encoding, errors="replace")
            text = _strip_html(raw_text)

            return {
                "accession": acc,
                "filed_at": filing_dates[i],
                "report_date": rdate,
                "raw_url": raw_url,
                "text": text,
            }

    raise ValueError(f"No 10-K found for {ticker!r} with reportDate in {fiscal_year}")


def _detect_encoding(raw: bytes) -> str:
    """Detect encoding from BOM or HTTP-equiv meta; fall back to utf-8."""
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    # Check for charset in first 2 KB of HTML
    head = raw[:2048].decode("ascii", errors="replace")
    m = re.search(r'charset=["\']?([\w-]+)', head, re.IGNORECASE)
    if m:
        return m.group(1)
    return "utf-8"


class _TextExtractor(HTMLParser):
    """Extracts visible text from HTML.

    Emits \\n\\n after block-level elements so the downstream paragraph-aware
    chunker can split on natural boundaries.
    Skips script, style, and hidden-attribute elements.
    """

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0  # nesting depth of skipped tags

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr_dict = dict(attrs)
        # Skip hidden elements
        style = attr_dict.get("style", "")
        if tag in ("script", "style") or "display:none" in style.replace(" ", ""):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _SELF_CLOSE_TAGS:
            self._parts.append("\n\n")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of spaces/tabs within a line, but preserve paragraph breaks.
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
        # Collapse 3+ blank lines into 2 (one paragraph break).
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
        return text.strip()


def _strip_html(html: str) -> str:
    """Remove HTML markup, preserving paragraph structure as \\n\\n separators."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()
