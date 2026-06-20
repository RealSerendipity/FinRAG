"""Query rewriting for under-specified retrieval (Wave 3e).

Three independent rewrites, each addressing a different failure mode of a raw
user query:

- `normalize_query`  — deterministic clean-up (whitespace, common finance
  abbreviations, unit words). No LLM; cheap and safe.
- `multi_query`      — LLM expands one query into several paraphrases so a single
  awkward phrasing does not sink recall (each is retrieved, results fused).
- `hyde`             — LLM writes a hypothetical answer passage; embedding *that*
  (HyDE, Gao 2022) often lands closer to real answer chunks than the question.

Public surface
--------------
- `normalize_query(q)` -> str
- `multi_query(q, n)` -> list[str]   (always includes the normalized original)
- `hyde(q)` -> str
"""

from __future__ import annotations

import re

from src.llm import chat

# Small, high-precision finance abbreviation expansions. Kept deliberately tiny —
# aggressive expansion hurts lexical precision more than it helps recall.
_ABBREVIATIONS = {
    r"\br&d\b": "research and development",
    r"\bcapex\b": "capital expenditures",
    r"\bopex\b": "operating expenses",
    r"\bcogs\b": "cost of goods sold",
    r"\beps\b": "earnings per share",
    r"\byoy\b": "year over year",
    r"\bsg&a\b": "selling general and administrative",
}


def normalize_query(q: str) -> str:
    """Deterministic clean-up: collapse whitespace, expand finance abbreviations."""
    text = re.sub(r"\s+", " ", q).strip()
    low = text.lower()
    for pattern, expansion in _ABBREVIATIONS.items():
        low = re.sub(pattern, expansion, low)
    return low


_MULTI_SYSTEM = (
    "You rewrite a financial-disclosure search query into diverse paraphrases to "
    "improve retrieval recall over SEC filings. Output ONLY the paraphrases, one "
    "per line, no numbering, no commentary. Keep each self-contained and specific."
)


def multi_query(q: str, n: int = 3) -> list[str]:
    """Return the normalized query plus up to n LLM paraphrases (deduped)."""
    base = normalize_query(q)
    user = f"Query: {q}\n\nWrite {n} alternative phrasings."
    try:
        resp = chat(messages=[{"role": "user", "content": user}], system=_MULTI_SYSTEM)
    except Exception:
        return [base]  # degrade to the original on any LLM error
    variants = [base]
    seen = {base}
    for line in resp.text.splitlines():
        cand = re.sub(r"^\s*[-*\d.)]+\s*", "", line).strip()
        if cand and cand.lower() not in seen:
            seen.add(cand.lower())
            variants.append(cand)
        if len(variants) >= n + 1:
            break
    return variants


_HYDE_SYSTEM = (
    "You are a financial analyst. Write a short, factual paragraph (2-4 sentences) "
    "that would plausibly appear in a 10-K/10-Q and that directly answers the "
    "question. Invent specific-sounding figures if needed — this text is used only "
    "as a retrieval probe, never shown to a user. Output the paragraph only."
)


def hyde(q: str) -> str:
    """Return a hypothetical answer passage to embed instead of the raw query."""
    try:
        resp = chat(messages=[{"role": "user", "content": f"Question: {q}"}], system=_HYDE_SYSTEM)
    except Exception:
        return normalize_query(q)
    return resp.text.strip() or normalize_query(q)
