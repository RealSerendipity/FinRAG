"""RAG pipeline: retrieve → prompt → LLM → validated Answer.

Public surface
--------------
- `ask(question, *, ticker, period, top_k)` → Answer
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.financial.schemas import Answer
from src.llm import chat
from src.retrieve import retrieve

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "answer_v1.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()


def ask(
    question: str,
    *,
    ticker: str | None = None,
    period: str | None = None,
    top_k: int = 10,
) -> Answer:
    """Retrieve relevant chunks and generate a cited answer.

    Raises ValueError if the LLM returns citations pointing to non-existent chunk IDs.
    """
    chunks = retrieve(question, ticker=ticker, period=period, top_k=top_k)
    if not chunks:
        raise ValueError("No chunks found for this query. Run ingest first.")

    # Format context for the prompt.
    context = "\n\n".join(
        f"[chunk_id={c['id']}]\n{c['content']}" for c in chunks
    )
    prompt = (
        _PROMPT_TEMPLATE
        .replace("{chunks}", context)
        .replace("{question}", question)
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
