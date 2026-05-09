"""SEC EDGAR API client: CIK lookup and 10-K text fetch.

Public surface
--------------
- `company_info_for_ticker(ticker)` — returns {"cik": int, "name": str}
- `cik_for_ticker(ticker)` — returns the integer CIK for a ticker symbol
- `fetch_10k(ticker, fiscal_year)` — returns {accession, filed_at, report_date, raw_url, text}
  for the 10-K whose period-of-report falls in `fiscal_year`
"""

from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser

from ..clients import edgar as edgar_client

_ticker_info_cache: dict[str, dict] | None = None  # {TICKER: {"cik": int, "name": str}}

_BLOCK_TAGS = frozenset(
    "p div h1 h2 h3 h4 h5 h6 li tr td th section article header footer "
    "blockquote pre ul ol dl dt dd table caption".split()
)
_SELF_CLOSE_TAGS = frozenset(["br", "hr"])
# All HTML void elements — they have no closing tag, so handle_endtag is never called for them.
# Must not increment _skip_depth for these when inside a hidden region.
_VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)


def company_info_for_ticker(ticker: str) -> dict:
    """Return {"cik": int, "name": str} for a ticker, using a cached company list.

    Raises ValueError if the ticker is not found in the EDGAR company list.
    """
    global _ticker_info_cache
    if _ticker_info_cache is None:
        data = json.loads(edgar_client.get_tickers())
        _ticker_info_cache = {
            v["ticker"].upper(): {"cik": int(v["cik_str"]), "name": v["title"]}
            for v in data.values()
        }
    info = _ticker_info_cache.get(ticker.upper())
    if info is None:
        raise ValueError(f"Ticker {ticker!r} not found in EDGAR company list")
    return info


def cik_for_ticker(ticker: str) -> int:
    """Return the integer CIK for a ticker symbol."""
    return company_info_for_ticker(ticker)["cik"]


def _iter_filing_pages(subs: dict) -> list[dict]:
    """Yield the recent filings dict, then any paginated historical filing pages."""
    pages = [subs["filings"]["recent"]]
    for extra in subs["filings"].get("files", []):
        extra_data = json.loads(edgar_client.get_submissions_page(extra["name"]))
        pages.append(extra_data)
    return pages


def fetch_10k(ticker: str, fiscal_year: int) -> dict:
    """Fetch the 10-K whose period-of-report (reportDate) falls in `fiscal_year`.

    Returns a dict with keys: accession, filed_at, report_date, raw_url, text.
    Raises ValueError if no matching 10-K is found.
    """
    cik = cik_for_ticker(ticker)
    subs = json.loads(edgar_client.get_submissions(cik))

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
            report_date = report_dates[i] if i < len(report_dates) else ""
            if not report_date or not report_date.startswith(str(fiscal_year)):
                continue

            accession = accessions[i]  # e.g. "0000320193-24-000073"
            accession_nodash = accession.replace("-", "")
            primary_doc = primary_docs[i]
            raw_url = edgar_client.document_url(cik, accession_nodash, primary_doc)

            time.sleep(0.1)  # EDGAR courtesy rate limit
            raw_bytes = edgar_client.get_document(cik, accession_nodash, primary_doc)
            # Use httpx-detected encoding, fall back to latin-1 (common for older SEC filings).
            encoding = _detect_encoding(raw_bytes)
            raw_text = raw_bytes.decode(encoding, errors="replace")
            text = _strip_html(raw_text)

            return {
                "accession": accession,
                "filed_at": filing_dates[i],
                "report_date": report_date,
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
    charset_match = re.search(r'charset=["\']?([\w-]+)', head, re.IGNORECASE)
    if charset_match:
        return charset_match.group(1)
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
            # Count every nested non-void open tag so its close tag can balance the depth.
            # Use _VOID_TAGS (not _SELF_CLOSE_TAGS) — void elements never fire handle_endtag.
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in _SELF_CLOSE_TAGS:
            self._parts.append("\n\n")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            # Every close tag balances one open tag inside the skip region.
            self._skip_depth = max(0, self._skip_depth - 1)
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
