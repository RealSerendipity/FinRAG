"""Wave 2 eval metrics.

Retrieval metrics are pure functions over relevance ranks so they can be
unit-tested without a database. Generation metrics call the configured judge
LLM (`LLM_JUDGE_PROVIDER` / `LLM_JUDGE_MODEL`) and fall back to a cheap Gemini
model when the primary judge errors.

Ground-truth relevance follows the Wave 1.5 convention: an OR-of-AND keyword
spec — a chunk is relevant when ANY group's substrings ALL appear in the chunk
content (case-insensitive, whitespace-normalized). This avoids chunk-id labels
that shift on re-ingest, at the cost of some noise in the recall denominator.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm import chat, judge_chat  # noqa: E402

# Fallback judge used when the configured judge errors (rate limit, key, ...).
FALLBACK_JUDGE = ("gemini", "gemini-2.5-flash-lite")


# --------------------------------------------------------------------------- #
# Relevance matching
# --------------------------------------------------------------------------- #
def _norm(text: str) -> str:
    # Filings contain non-breaking spaces (e.g. "$132.4\xa0billion");
    # collapse all whitespace so keyword specs can use plain spaces.
    return re.sub(r"\s+", " ", text).lower()


def matches(content: str, groups: list[list[str]]) -> bool:
    """True when ANY group's terms ALL appear in content (OR-of-AND)."""
    if not groups:
        return False
    text = _norm(content)
    return any(all(_norm(term) in text for term in grp) for grp in groups)


def relevant_ranks(contents: list[str], groups: list[list[str]]) -> list[int]:
    """1-based ranks of relevant items in a ranked content list."""
    return [rank for rank, c in enumerate(contents, start=1) if matches(c, groups)]


# --------------------------------------------------------------------------- #
# Retrieval metrics (pure)
# --------------------------------------------------------------------------- #
def hit_at_k(rel_ranks: list[int], k: int) -> bool:
    return any(r <= k for r in rel_ranks)


def recall_at_k(rel_ranks: list[int], k: int, total_rel: int) -> float | None:
    """Local recall: |relevant in top-k| / total relevant found in the probe."""
    if total_rel == 0:
        return None
    return sum(1 for r in rel_ranks if r <= k) / total_rel


def mrr(rel_ranks: list[int]) -> float:
    """Reciprocal rank of the first relevant item; 0 when none found."""
    return 1.0 / rel_ranks[0] if rel_ranks else 0.0


def ndcg_at_k(rel_ranks: list[int], k: int, total_rel: int) -> float | None:
    """Binary-relevance nDCG@k; ideal ranking packs min(total_rel, k) at top."""
    if total_rel == 0:
        return None
    dcg = sum(1.0 / math.log2(r + 1) for r in rel_ranks if r <= k)
    ideal_n = min(total_rel, k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    return dcg / idcg if idcg else 0.0


def doc_coverage_at_k(
    accessions_ranked: list[str], expected: list[str], k: int
) -> float | None:
    """Fraction of expected documents present in the top-k ranked accessions."""
    if not expected:
        return None
    seen = set(accessions_ranked[:k])
    return sum(1 for acc in expected if acc in seen) / len(expected)


# --------------------------------------------------------------------------- #
# Generation metrics (LLM judge)
# --------------------------------------------------------------------------- #
_JUDGE_SYSTEM = (
    "You are a strict evaluator of RAG answers over SEC filings.\n"
    "Given QUESTION, EXPECTED (ground-truth reference), ANSWER, and the CITED "
    "CHUNKS the answer relies on, return JSON exactly:\n"
    '  {"faithful": true|false, "relevant": true|false, "correct": true|false, '
    '"reason": "<one short sentence>"}\n'
    "- faithful: every factual claim in ANSWER is directly supported by the "
    "verbatim CITED CHUNKS; anything added or unsupported makes it false.\n"
    "- relevant: ANSWER actually addresses what QUESTION asks (even if wrong).\n"
    "- correct: ANSWER agrees with EXPECTED on the primary fact(s) the QUESTION "
    "asks for; numeric values must match (formatting and rounding to the same "
    "precision are fine). Extra correct detail is fine, and omitting secondary "
    "context that EXPECTED mentions (e.g. growth rates or drivers when the "
    "question asks only for a value) does NOT make it incorrect.\n"
    "Return JSON only, no prose, no code fences."
)


def parse_json_obj(raw: str, required_key: str) -> dict | None:
    """Extract the first JSON object containing required_key from LLM output."""
    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    span = re.search(r"\{.*\}", raw, re.DOTALL)
    if span:
        candidates.append(span.group())
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and required_key in data:
            return data
    return None


def judge_answer(
    question: str,
    expected_answer: str,
    answer_text: str,
    cited_excerpts: list[tuple[int, str]],
) -> dict:
    """Judge one answer. Returns dict with faithful/relevant/correct (bool|None),
    reason, and judge ("primary" | "fallback" | "error: ...")."""
    excerpts = "\n\n".join(
        f"[chunk_id={cid}]\n{content}" for cid, content in cited_excerpts
    )
    user = (
        f"QUESTION:\n{question}\n\n"
        f"EXPECTED:\n{expected_answer}\n\n"
        f"ANSWER:\n{answer_text}\n\n"
        f"CITED CHUNKS:\n{excerpts or '<none>'}"
    )
    verdict_src = "primary"
    try:
        resp = judge_chat(messages=[{"role": "user", "content": user}], system=_JUDGE_SYSTEM)
    except Exception:
        verdict_src = "fallback"
        try:
            provider, model = FALLBACK_JUDGE
            resp = chat(
                messages=[{"role": "user", "content": user}],
                provider=provider,
                model=model,
                system=_JUDGE_SYSTEM,
            )
        except Exception as exc:
            return _judge_failure(f"error: {type(exc).__name__}: {exc}")
    data = parse_json_obj(resp.text, "faithful")
    if data is None:
        return _judge_failure(f"error: unparseable judge output: {resp.text[:120]!r}")
    return {
        "faithful": bool(data["faithful"]),
        "relevant": bool(data.get("relevant", False)),
        "correct": bool(data.get("correct", False)),
        "reason": str(data.get("reason", "")).strip(),
        "judge": verdict_src,
    }


def _judge_failure(detail: str) -> dict:
    return {
        "faithful": None,
        "relevant": None,
        "correct": None,
        "reason": detail,
        "judge": detail,
    }


def mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None
