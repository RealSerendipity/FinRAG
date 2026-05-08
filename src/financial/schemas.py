"""Pydantic models for filings, chunks, and answers."""

from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    chunk_id: int
    quote: str  # verbatim short excerpt from the chunk that supports the answer


class Answer(BaseModel):
    text: str
    citations: list[Citation]

    @property
    def is_sufficient(self) -> bool:
        """False when the LLM reported insufficient context (no citations)."""
        return len(self.citations) > 0


class Filing(BaseModel):
    """Metadata for an ingested SEC filing."""

    ticker: str
    filing_type: str
    period: str
    accession: str
    filed_at: str
    raw_url: str | None = None
