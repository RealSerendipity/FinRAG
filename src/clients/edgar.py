"""Raw EDGAR API calls. All HTTP goes through clients._http.fetch()."""
from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field

from src import config
from src.clients import _http


class EdgarCompanyInfo(BaseModel):
    """Validated EDGAR company identity."""

    model_config = ConfigDict(extra="forbid")

    cik: int = Field(gt=0)
    name: str = Field(min_length=1)


class EdgarFiling(BaseModel):
    """Validated EDGAR filing payload used by ingest."""

    model_config = ConfigDict(extra="forbid")

    accession: str
    filed_at: datetime.date
    report_date: datetime.date
    raw_url: str
    text: str


def _headers() -> dict[str, str]:
    return {"User-Agent": config.edgar_user_agent()}

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_SUBMISSIONS_EXTRA_URL = "https://data.sec.gov/submissions/{name}"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"


def get_tickers() -> bytes:
    """Fetch the full EDGAR company tickers list."""
    return _http.fetch(_TICKERS_URL, headers=_headers())


def get_submissions(cik: int) -> bytes:
    """Fetch the submissions JSON for a company by CIK."""
    return _http.fetch(_SUBMISSIONS_URL.format(cik=cik), headers=_headers())


def get_submissions_page(name: str) -> bytes:
    """Fetch a paginated historical filings page by filename."""
    return _http.fetch(_SUBMISSIONS_EXTRA_URL.format(name=name), headers=_headers())


def document_url(cik: int, accession_nodash: str, doc: str) -> str:
    """Build the EDGAR archive URL for a filing document (no HTTP call)."""
    return _ARCHIVE_URL.format(cik=cik, accession_nodash=accession_nodash, doc=doc)


def get_document(cik: int, accession_nodash: str, doc: str) -> bytes:
    """Fetch a 10-K or other filing document from EDGAR archives."""
    return _http.fetch(document_url(cik, accession_nodash, doc), headers=_headers())
