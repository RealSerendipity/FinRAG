"""Raw EDGAR API calls. All HTTP goes through clients._http.fetch()."""
from __future__ import annotations

import os

from src.clients import _http

_USER_AGENT = os.getenv("EDGAR_USER_AGENT", "finrag/0.1 finrag-user@example.com")
HEADERS: dict[str, str] = {"User-Agent": _USER_AGENT}

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_SUBMISSIONS_EXTRA_URL = "https://data.sec.gov/submissions/{name}"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"


def get_tickers() -> bytes:
    """Fetch the full EDGAR company tickers list."""
    return _http.fetch(_TICKERS_URL, headers=HEADERS)


def get_submissions(cik: int) -> bytes:
    """Fetch the submissions JSON for a company by CIK."""
    return _http.fetch(_SUBMISSIONS_URL.format(cik=cik), headers=HEADERS)


def get_submissions_page(name: str) -> bytes:
    """Fetch a paginated historical filings page by filename."""
    return _http.fetch(_SUBMISSIONS_EXTRA_URL.format(name=name), headers=HEADERS)


def document_url(cik: int, accession_nodash: str, doc: str) -> str:
    """Build the EDGAR archive URL for a filing document (no HTTP call)."""
    return _ARCHIVE_URL.format(cik=cik, accession_nodash=accession_nodash, doc=doc)


def get_document(cik: int, accession_nodash: str, doc: str) -> bytes:
    """Fetch a 10-K or other filing document from EDGAR archives."""
    return _http.fetch(document_url(cik, accession_nodash, doc), headers=HEADERS)
