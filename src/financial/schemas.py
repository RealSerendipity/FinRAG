"""Pydantic models for filings, chunks, and answers.

Wave 1b: Citation + Answer (minimal set needed for cited RAG).
Wave 1c will extend with Filing and Chunk ingestion models.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


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
