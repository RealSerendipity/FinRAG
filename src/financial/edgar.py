"""SEC EDGAR API client: CIK lookup and filing text fetch.

Public surface
--------------
- `company_info_for_ticker(ticker)` — returns EdgarCompanyInfo
- `cik_for_ticker(ticker)` — returns the integer CIK for a ticker symbol
- `fetch_filing(ticker, form_type, period)` — returns EdgarFiling for the matching filing
"""

from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser

from ..clients import edgar as edgar_client

_ticker_info_cache: dict[str, edgar_client.EdgarCompanyInfo] | None = None

# Forms that can appear multiple times per year; year-level period is ambiguous for them.
_MULTI_FILING_FORMS = frozenset({"8-K", "10-Q"})

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


def company_info_for_ticker(ticker: str) -> edgar_client.EdgarCompanyInfo:
    """Return validated company info for a ticker, using a cached company list.

    Raises ValueError if the ticker is not found in the EDGAR company list.
    """
    global _ticker_info_cache
    if _ticker_info_cache is None:
        data = json.loads(edgar_client.get_tickers())
        _ticker_info_cache = {
            v["ticker"].upper(): edgar_client.EdgarCompanyInfo.model_validate(
                {"cik": v["cik_str"], "name": v["title"]}
            )
            for v in data.values()
        }
    info = _ticker_info_cache.get(ticker.upper())
    if info is None:
        raise ValueError(f"Ticker {ticker!r} not found in EDGAR company list")
    return info


def cik_for_ticker(ticker: str) -> int:
    """Return the integer CIK for a ticker symbol."""
    return company_info_for_ticker(ticker).cik


def _iter_filing_pages(subs: dict) -> list[dict]:
    """Yield the recent filings dict, then any paginated historical filing pages."""
    pages = [subs["filings"]["recent"]]
    for extra in subs["filings"].get("files", []):
        extra_data = json.loads(edgar_client.get_submissions_page(extra["name"]))
        pages.append(extra_data)
    return pages


def _match_period(period: str, report_date: str) -> bool:
    """Return True if report_date (YYYY-MM-DD) matches the period string.

    Supported period formats:
    - "FY2024"     — year match: report_date starts with "2024"
    - "2024-05-10" — exact date match (8-K, DEF 14A, precise 10-Q)
    - "2024"       — year-level match (any form type)

    Quarter-style strings (Q1-YYYY) are intentionally unsupported: SEC fiscal
    quarters are company-specific and do not map to fixed calendar months.
    Pass the exact reportDate instead.
    """
    if not report_date:
        return False
    if period.startswith("FY"):
        return report_date.startswith(period[2:])
    # "YYYY-MM-DD" exact match
    if len(period) == 10 and period[4] == "-" and period[7] == "-":
        return report_date == period
    # bare year fallback
    return report_date.startswith(period)


def _is_year_level(period: str) -> bool:
    """Return True if period is a year-level specifier (FY2024 or bare 2024)."""
    return period.startswith("FY") or (len(period) == 4 and period.isdigit())


def fetch_filing(ticker: str, form_type: str, period: str) -> edgar_client.EdgarFiling:
    """Fetch the first EDGAR filing matching form_type whose reportDate matches period.

    Supported form types: 10-K, 10-Q, 8-K, 20-F, DEF 14A.
    Returns an EdgarFiling with accession, filed_at, report_date, raw_url, and text.
    Raises ValueError if no matching filing is found.

    8-K and 10-Q occur multiple times per year; year-level periods (e.g. FY2024, 2024)
    are rejected for these forms — provide an exact date: YYYY-MM-DD.
    """
    if form_type in _MULTI_FILING_FORMS and _is_year_level(period):
        raise ValueError(
            f"{form_type} filings occur multiple times per year. "
            f"Provide an exact reportDate instead of a year-level period: "
            f"--period YYYY-MM-DD"
        )
    cik = cik_for_ticker(ticker)
    subs = json.loads(edgar_client.get_submissions(cik))

    for page in _iter_filing_pages(subs):
        forms: list[str] = page["form"]
        filing_dates: list[str] = page["filingDate"]
        report_dates: list[str] = page.get("reportDate", [""] * len(forms))
        accessions: list[str] = page["accessionNumber"]
        primary_docs: list[str] = page["primaryDocument"]

        for i, form in enumerate(forms):
            if form != form_type:
                continue
            # Use reportDate (period-of-report) to match period, not filingDate.
            report_date = report_dates[i] if i < len(report_dates) else ""
            if not _match_period(period, report_date):
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

            return edgar_client.EdgarFiling.model_validate(
                {
                    "accession": accession,
                    "filed_at": filing_dates[i],
                    "report_date": report_date,
                    "raw_url": raw_url,
                    "text": text,
                }
            )

    raise ValueError(
        f"No {form_type} found for {ticker!r} with period matching {period!r}"
    )


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
            if tag not in _VOID_TAGS:
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
            # Void elements written as self-closing (<br/>, <img/>) cause HTMLParser to
            # call handle_startendtag → handle_starttag + handle_endtag.  handle_starttag
            # correctly skips incrementing for void tags, so handle_endtag must also skip
            # decrementing — otherwise the depth goes negative and hidden text leaks out.
            if tag not in _VOID_TAGS:
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
