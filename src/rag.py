"""RAG pipeline: retrieve → prompt → LLM → validated Answer.

Public surface
--------------
- `ask(question, *, ticker, period, top_k)` → Answer
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.financial.schemas import Answer
from src.llm import chat
from src.retrieve import retrieve

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "answer_v1.1.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()
_PERIOD_PATTERN = re.compile(r"^(?:FY\d{4}|\d{4}|\d{4}-\d{2}-\d{2})$")


class RagAskInput(BaseModel):
    """Validated input for the RAG ask entry point."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    ticker: str | None = None
    period: str | None = None
    top_k: int = Field(default=5, ge=1, le=100)

    @field_validator("question", mode="before")
    @classmethod
    def _normalize_question(cls, value: Any) -> str:
        if value is None:
            return ""  # min_length=1 will reject this
        return str(value).strip()

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().upper()
        return text or None

    @field_validator("period", mode="before")
    @classmethod
    def _normalize_period(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("period", mode="after")
    @classmethod
    def _validate_period(cls, value: str | None) -> str | None:
        if value is not None and not _PERIOD_PATTERN.fullmatch(value):
            raise ValueError("period must match FY followed by 4 digits, YYYY, or YYYY-MM-DD")
        return value


def ask(
    question: str,
    *,
    ticker: str | None = None,
    period: str | None = None,
    top_k: int = 5,
) -> Answer:
    """Retrieve relevant chunks and generate a cited answer.

    Raises ValueError if the LLM returns citations pointing to non-existent chunk IDs.
    """
    input_data = RagAskInput(question=question, ticker=ticker, period=period, top_k=top_k)
    chunks = retrieve(
        input_data.question,
        ticker=input_data.ticker,
        period=input_data.period,
        top_k=input_data.top_k,
    )
    if not chunks:
        raise ValueError("No chunks found for this query. Run ingest first.")

    # Format context for the prompt.
    context = "\n\n".join(
        f"[chunk_id={c['id']}]\n{c['content']}" for c in chunks
    )
    prompt = (
        _PROMPT_TEMPLATE
        .replace("{chunks}", context)
        .replace("{question}", input_data.question)
    )

    resp = chat(messages=[{"role": "user", "content": prompt}])

    # Extract JSON from LLM response.
    # Strategy: try raw → fenced block → first-`{`-to-last-`}` span.
    raw = resp.text.strip()
    data: dict | None = None
    candidates: list[str] = [raw]

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))

    span = re.search(r"\{.*\}", raw, re.DOTALL)  # greedy: first { to last }
    if span:
        candidates.append(span.group())

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue

    if data is None:
        raise ValueError(f"LLM did not return valid JSON. Response: {raw!r}")

    answer = Answer.model_validate(data)  # type: ignore[arg-type]

    # Hallucination contract: every cited chunk_id must exist in retrieved chunks.
    # Skip when LLM reported insufficient context (empty citations is valid then).
    if answer.is_sufficient:
        valid_ids = {c["id"] for c in chunks}
        bad = [cit.chunk_id for cit in answer.citations if cit.chunk_id not in valid_ids]
        if bad:
            raise ValueError(
                f"LLM cited chunk_id(s) {bad} that were not in the retrieved context. "
                "Likely hallucination — answer rejected."
            )

    return answer
