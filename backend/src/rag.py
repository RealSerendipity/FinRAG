"""RAG pipeline: retrieve → prompt → LLM → validated Answer.

Public surface
--------------
- `ask(question, *, ticker, period, top_k)` → Answer
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import config, guardrails, obs
from src.financial.schemas import Answer
from src.llm import chat
from src.retrieve import retrieve

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "answer_v1.1.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()
_PERIOD_PATTERN = re.compile(r"^(?:FY\d{4}|\d{4}|\d{4}-\d{2}-\d{2})$")

# Distinctive fragments of the answer prompt. If one shows up in a generated
# answer, the model is echoing its instructions (prompt extraction) — the output
# guardrail withholds the answer.
_PROMPT_SECRETS = ("Base every claim strictly on the context",)


class RagAskInput(BaseModel):
    """Validated input for the RAG ask entry point."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    ticker: str | None = None
    period: str | None = None
    top_k: int = Field(default=5, ge=1, le=config.MAX_TOP_K)

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


def _norm_ws(text: str) -> str:
    """Whitespace-normalized, case-folded form used for quote-in-chunk matching."""
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _quote_verified(quote: str, chunk: dict) -> bool:
    """True when `quote` occurs (whitespace-normalized) in the chunk text the model saw."""
    q = _norm_ws(quote)
    return bool(q) and q in _norm_ws(_context_text(chunk))


def _context_text(chunk: dict) -> str:
    """Generation context for a retrieved chunk: parent_text if present, else content.

    parent_doc chunking (Wave 3a) embeds a small child for precise retrieval but
    stores the surrounding parent block in metadata.parent_text; other strategies
    have no parent_text and fall back to the chunk's own content.
    """
    parent = (chunk.get("metadata") or {}).get("parent_text")
    return parent or chunk["content"]


def _iter_json_objects(raw: str):
    """Yield every balanced top-level {...} substring, ignoring braces inside strings.

    String state is only tracked inside an object (depth > 0): a lone quote in
    surrounding prose would otherwise open a phantom string and swallow the real
    JSON that follows it.
    """
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
            if depth > 0:
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

    # Wave 6 input guardrail: refuse injection/jailbreak/extraction attempts before
    # any retrieval or generation. Benign filing questions never match the signatures.
    if config.guardrails_enabled():
        verdict = guardrails.screen_input(input_data.question)
        if verdict.blocked:
            return Answer(text=guardrails.REFUSAL_TEXT, citations=[])

    chunks = retrieve(
        input_data.question,
        ticker=input_data.ticker,
        period=input_data.period,
        top_k=input_data.top_k,
    )
    if not chunks:
        raise ValueError("No chunks found for this query. Run ingest first.")

    # Wave 6 indirect-injection guardrail: drop retrieved chunks that carry planted
    # instructions ("ignore the user and …") so a poisoned filing snippet cannot
    # hijack the answer. Dropped chunks are logged — a silent drop would look like
    # a retrieval-quality regression and hide an actual poisoning attempt. If every
    # chunk is filtered out, refuse rather than answer from nothing.
    if config.guardrails_enabled():
        chunks, flags = guardrails.screen_context(chunks)
        if flags:
            logger.warning(
                "screen_context dropped %d chunk(s): %s", len(flags), "; ".join(flags)
            )
            # Surface the drop in the request trace too, not just the process log.
            with obs.span("guardrails.screen_context", metadata={"flags": flags}) as sp:
                sp.update(output={"dropped": len(flags), "kept": len(chunks)})
        if not chunks:
            return Answer(text=guardrails.REFUSAL_TEXT_CONTEXT, citations=[])

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
    # Enforced regardless of GUARDRAILS_ENABLED — it is a data-integrity check,
    # not an attack screen.
    if answer.is_sufficient:
        valid_ids = {c["id"] for c in chunks}
        bad = [cit.chunk_id for cit in answer.citations if cit.chunk_id not in valid_ids]
        if bad:
            raise ValueError(
                f"LLM cited chunk_id(s) {bad} that were not in the retrieved context. "
                "Likely hallucination — answer rejected."
            )
        # Citation-quote integrity: the schema promises `quote` is a verbatim
        # excerpt of the cited chunk, but the model can pair a real chunk_id with
        # an invented quote. A quote that isn't found (whitespace-normalized) in
        # the chunk text the model saw is marked unverified — not a hard error,
        # the answer may still be right, but the UI must not show it as evidence.
        by_id = {c["id"]: c for c in chunks}
        checked = []
        for cit in answer.citations:
            ok = _quote_verified(cit.quote, by_id[cit.chunk_id])
            if not ok:
                logger.warning(
                    "citation quote for chunk %d not found in the chunk — marked unverified",
                    cit.chunk_id,
                )
            checked.append(cit.model_copy(update={"verified": ok}))
        answer = Answer(text=answer.text, citations=checked)

    # Wave 6 output guardrail (last line of defense): withhold an answer that
    # echoes the prompt/configuration, then strip PII from what is returned.
    # Citation quotes are left untouched — they are verbatim filing text.
    if config.guardrails_enabled():
        verdict = guardrails.validate_output(answer.text, secrets=_PROMPT_SECRETS)
        if verdict.blocked:
            logger.warning("validate_output withheld an answer: %s", verdict.detail)
            return Answer(text=guardrails.REFUSAL_TEXT_OUTPUT, citations=[])
        redacted, n_pii = guardrails.redact_pii(answer.text)
        if n_pii:
            answer = Answer(text=redacted, citations=answer.citations)

    return answer
