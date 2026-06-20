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


def _context_text(chunk: dict) -> str:
    """Generation context for a retrieved chunk: parent_text if present, else content.

    parent_doc chunking (Wave 3a) embeds a small child for precise retrieval but
    stores the surrounding parent block in metadata.parent_text; other strategies
    have no parent_text and fall back to the chunk's own content.
    """
    parent = (chunk.get("metadata") or {}).get("parent_text")
    return parent or chunk["content"]


def _iter_json_objects(raw: str):
    """Yield every balanced top-level {...} substring, ignoring braces inside strings."""
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(raw):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                yield raw[start : i + 1]


def _extract_answer_obj(raw: str) -> dict | None:
    """Return the last Answer-shaped JSON object in raw, else the last valid object.

    Prefers the final object that has both `text` and `citations` (the schema) so a
    reasoning model's last answer wins over its intermediate JSON attempts.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    objs: list[dict] = []
    for candidate in ([raw] if raw.startswith("{") else []) + \
            ([fenced.group(1)] if fenced else []) + list(_iter_json_objects(raw)):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objs.append(obj)
    shaped = [o for o in objs if "text" in o and "citations" in o]
    if shaped:
        return shaped[-1]
    return objs[-1] if objs else None


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

    # Format context for the prompt. parent_doc chunks store the larger parent
    # block in metadata.parent_text — feed that to the LLM (retrieve small/precise,
    # generate with full context) while citations still map to the retrieved chunk_id.
    context = "\n\n".join(
        f"[chunk_id={c['id']}]\n{_context_text(c)}" for c in chunks
    )
    prompt = (
        _PROMPT_TEMPLATE
        .replace("{chunks}", context)
        .replace("{question}", input_data.question)
    )

    resp = chat(messages=[{"role": "user", "content": prompt}])

    # Extract the Answer JSON from the LLM response. Reasoning-capable models may
    # emit chain-of-thought and *several* JSON objects (intermediate attempts) with
    # prose between them, so a single first-`{`-to-last-`}` span fails. We scan all
    # balanced top-level {...} objects and keep the LAST Answer-shaped one (the
    # model's final answer), falling back to the raw/fenced text.
    raw = resp.text.strip()
    data = _extract_answer_obj(raw)
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
