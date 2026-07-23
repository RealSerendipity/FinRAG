"""Wave 1.5 mini-eval — 7 hand-curated items over real AAPL 10-K (FY2024).

Usage
-----
    uv run python eval/mini_eval.py

Prerequisites
-------------
- AAPL FY2024 10-K must be ingested:
      uv run finrag ingest --tickers AAPL --year 2024
- `.env` must set `LLM_PROVIDER`, `NVIDIA_API_KEY`, `DATABASE_URL`.
- For faithfulness, set `LLM_JUDGE_PROVIDER` and `LLM_JUDGE_MODEL` (defaults
  to `LLM_PROVIDER`, which is fine for a quick sanity check but in production
  the judge should be a stronger / different model).

Metrics
-------
- **hit@k**       — binary: any relevant chunk in top-k.
- **recall@k**    — |relevant in top-k| / |relevant in top-K_max| (K_max=`PROBE_K`).
                    This is a *local* recall over what the system can find at
                    all, not absolute recall over the corpus.
- **MRR**         — reciprocal rank of the first relevant chunk in the
                    top-K_max probe; 0 if none found.
- **nDCG@k**      — binary-relevance nDCG normalized against an ideal ranking
                    that packs all relevants found in top-K_max at the top.
- **citation validity** — structural:
      positive item: cited chunk overlaps the relevance predicate
      insufficient item: model says exactly `"Insufficient context"` and no citations
- **faithfulness** — `judge_chat` returns `{"faithful": bool, "reason": str}`
                     for each positive, sufficient-context answer, comparing
                     `answer.text` against the verbatim cited-chunk excerpts.

Ground truth is *approximate*: each item declares `relevance` as
OR-of-AND keyword groups; a chunk counts as relevant when any group's terms
all appear (case-insensitive). Tradeoff: avoids fragile chunk-id labels that
shift on re-ingest, accepts some noise in the recall denominator. ragas is
intentionally not used — it is not in this project's dependencies and Wave 2
is the place to wire a judge harness end-to-end.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.financial.schemas import Answer  # noqa: E402
from src.llm import judge_chat  # noqa: E402
from src.rag import ask  # noqa: E402
from src.retrieve import retrieve  # noqa: E402

TOP_K = 5
PROBE_K = 50  # widen probe to estimate the local recall denominator
REPORT_PATH = Path(__file__).parent / "reports" / "wave1_5_mini_eval.md"

# Each item targets the AAPL FY2024 10-K. `relevance` is an OR-of-AND keyword
# spec: a chunk is relevant when ANY group's substrings ALL appear in the
# chunk content (case-insensitive). Empty `relevance` ⇒ insufficient-context
# item; the model is expected to return `{"text":"Insufficient context",
# "citations":[]}`.
ITEMS: list[dict] = [
    {
        "id": "aapl-fy24-total-net-sales",
        "question": "What were Apple's total net sales for fiscal year 2024?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [["391,035"]],
        "notes": "Apple FY2024 total net sales: $391,035M.",
    },
    {
        "id": "aapl-fy24-iphone-net-sales",
        "question": "What were Apple's iPhone net sales in fiscal year 2024?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [["iphone", "201,183"]],
        "notes": "iPhone FY2024 net sales: $201,183M.",
    },
    {
        "id": "aapl-fy24-rd",
        "question": "How much did Apple spend on research and development in fiscal year 2024?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [["31,370"]],
        "notes": "R&D expense FY2024: $31,370M.",
    },
    {
        "id": "aapl-fy24-iphone16-launch",
        "question": "Which iPhone 16 models did Apple release during fiscal year 2024?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [["iphone 16"]],
        "notes": "iPhone 16, 16 Plus, 16 Pro, 16 Pro Max.",
    },
    {
        "id": "aapl-fy24-dividend-per-share",
        "question": "What quarterly cash dividend per share did Apple declare during fiscal 2024?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [["$0.25"]],
        "notes": "Quarterly dividend: $0.25 per share.",
    },
    {
        "id": "aapl-fy24-tax-rate-risk",
        "question": "What risks does Apple identify around changes in its effective tax rate?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [["effective tax rate"]],
        "notes": (
            "Risk factors mention tax-rate changes, new tax legislation, "
            "and additional liabilities."
        ),
    },
    {
        "id": "aapl-fy24-argentina-revenue-insufficient",
        "question": "What were Apple's net sales in Argentina in fiscal year 2024?",
        "ticker": "AAPL",
        "period": "2024-09-28",
        "relevance": [],
        "notes": (
            "10-K breaks geography by Americas/Europe/Greater China/Japan/"
            "Rest of Asia Pacific — no country-level Argentina figure."
        ),
    },
]


# --------------------------------------------------------------------------- #
# Metric helpers
# --------------------------------------------------------------------------- #
def _matches(content: str, groups: list[list[str]]) -> bool:
    if not groups:
        return False
    text = content.lower()
    return any(all(term.lower() in text for term in grp) for grp in groups)


def _relevant_ranks(chunks: list[dict], groups: list[list[str]]) -> list[int]:
    return [rank for rank, c in enumerate(chunks, start=1) if _matches(c["content"], groups)]


def _ndcg_at_k(rel_ranks: list[int], k: int, total_rel: int) -> float | None:
    """Binary-relevance nDCG@k. Ideal DCG packs min(total_rel, k) relevants at top.

    Returns None when there is no ground truth (total_rel == 0).
    """
    if total_rel == 0:
        return None
    dcg = sum(1.0 / math.log2(r + 1) for r in rel_ranks if r <= k)
    ideal_n = min(total_rel, k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    return dcg / idcg if idcg else 0.0


# --------------------------------------------------------------------------- #
# Faithfulness judge
# --------------------------------------------------------------------------- #
_JUDGE_PROMPT = (
    "You are a strict evaluator of RAG answer faithfulness.\n"
    "Given an ANSWER and the CITED CHUNKS it supposedly relies on, return JSON:\n"
    '  {"faithful": true|false, "reason": "<one short sentence>"}\n'
    "faithful=true ONLY if every factual claim in ANSWER is directly supported "
    "by the verbatim CITED CHUNKS. If anything is added, paraphrased imprecisely, "
    "or unsupported, faithful=false.\n"
    "Return JSON only, no prose, no code fences."
)


def _parse_judge_json(raw: str) -> dict | None:
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
        if isinstance(data, dict) and "faithful" in data:
            return data
    return None


def _judge_faithfulness(
    answer: Answer, retrieved_by_id: dict[int, str]
) -> tuple[bool | None, str]:
    if not answer.citations:
        return None, "no citations to judge"
    excerpts = "\n\n".join(
        f"[chunk_id={cit.chunk_id}]\n{retrieved_by_id.get(cit.chunk_id, '<missing>')}"
        for cit in answer.citations
    )
    user = f"ANSWER:\n{answer.text}\n\nCITED CHUNKS:\n{excerpts}"
    try:
        resp = judge_chat(
            messages=[{"role": "user", "content": user}],
            system=_JUDGE_PROMPT,
        )
    except Exception as exc:
        return None, f"judge error: {type(exc).__name__}: {exc}"
    data = _parse_judge_json(resp.text)
    if data is None:
        return None, f"judge output unparseable: {resp.text[:120]!r}"
    return bool(data["faithful"]), str(data.get("reason", "")).strip()


# --------------------------------------------------------------------------- #
# Per-item runner
# --------------------------------------------------------------------------- #
def _run_item(item: dict) -> dict:
    probe = retrieve(
        item["question"],
        ticker=item["ticker"],
        period=item["period"],
        top_k=PROBE_K,
    )
    top_k = probe[:TOP_K]
    id_to_index = {c["id"]: c["chunk_index"] for c in probe}
    id_to_content = {c["id"]: c["content"] for c in probe}

    relevance = item["relevance"]
    rel_ranks = _relevant_ranks(probe, relevance)
    total_rel = len(rel_ranks)

    if relevance:
        hit_at_k: bool | None = any(r <= TOP_K for r in rel_ranks)
        recall_at_k: float | None = (
            sum(1 for r in rel_ranks if r <= TOP_K) / total_rel if total_rel else None
        )
        mrr: float | None = (1.0 / rel_ranks[0]) if rel_ranks else 0.0
        ndcg: float | None = _ndcg_at_k(rel_ranks, TOP_K, total_rel)
    else:
        hit_at_k = recall_at_k = mrr = ndcg = None

    error: str | None = None
    answer: Answer | None = None
    cited_indexes: list[int] = []
    is_sufficient = False
    faithful: bool | None = None
    faith_reason = ""
    try:
        answer = ask(
            item["question"],
            ticker=item["ticker"],
            period=item["period"],
            top_k=TOP_K,
        )
        is_sufficient = answer.is_sufficient
        cited_idxs = {id_to_index.get(c.chunk_id) for c in answer.citations}
        cited_idxs.discard(None)
        cited_indexes = sorted(i for i in cited_idxs if i is not None)
        if relevance and is_sufficient:
            faithful, faith_reason = _judge_faithfulness(answer, id_to_content)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    if relevance:
        cited_ids = {cit.chunk_id for cit in (answer.citations if answer else [])}
        cited_chunks_relevant = any(
            _matches(c["content"], relevance) for c in top_k if c["id"] in cited_ids
        )
        citation_valid = is_sufficient and cited_chunks_relevant
    else:
        citation_valid = (
            answer is not None
            and not is_sufficient
            and answer.text.strip().lower() == "insufficient context"
        )

    return {
        "item": item,
        "retrieved_top_k_indexes": [c["chunk_index"] for c in top_k],
        "relevant_ranks": rel_ranks,
        "total_relevant_probe": total_rel,
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "mrr": mrr,
        "ndcg": ndcg,
        "answer_text": answer.text if answer is not None else "",
        "is_sufficient": is_sufficient,
        "cited_indexes": cited_indexes,
        "citation_valid": citation_valid,
        "faithful": faithful,
        "faith_reason": faith_reason,
        "error": error,
    }


# --------------------------------------------------------------------------- #
# Aggregation + IO
# --------------------------------------------------------------------------- #
def _check_env() -> None:
    required = ("DATABASE_URL", "NVIDIA_API_KEY", "LLM_PROVIDER")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        sys.exit(
            f"Missing required env vars: {missing}. "
            "Configure .env (LLM_PROVIDER, NVIDIA_API_KEY, DATABASE_URL) and "
            "ingest AAPL FY2024 via `uv run finrag ingest --tickers AAPL --year 2024` first."
        )


def _fmt_float(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return f"{value:.{digits}f}"


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _summary(results: list[dict]) -> dict:
    positives = [r for r in results if r["item"]["relevance"]]
    return {
        "n_total": len(results),
        "n_positive": len(positives),
        "n_insufficient": len(results) - len(positives),
        "hit_at_k": _mean([1.0 if r["hit_at_k"] else 0.0 for r in positives]),
        "recall_at_k": _mean([r["recall_at_k"] for r in positives]),
        "mrr": _mean([r["mrr"] for r in positives]),
        "ndcg_at_k": _mean([r["ndcg"] for r in positives]),
        "citation_validity": _mean([1.0 if r["citation_valid"] else 0.0 for r in results]),
        "faithfulness": _mean(
            [1.0 if r["faithful"] else 0.0 for r in positives if r["faithful"] is not None]
        ),
        "faith_judged": sum(1 for r in positives if r["faithful"] is not None),
        "errors": sum(1 for r in results if r["error"]),
    }


def _print_table(results: list[dict], s: dict) -> None:
    header = f"{'id':<46} {'hit':<4} {'rec':<5} {'mrr':<5} {'ndcg':<5} {'cite':<5} {'faith':<6}"
    print(header)
    print("-" * len(header))
    for r in results:
        hit = "—" if r["hit_at_k"] is None else ("yes" if r["hit_at_k"] else "no")
        cite = "yes" if r["citation_valid"] else "no"
        if r["faithful"] is None:
            faith = "—" if not r["item"]["relevance"] else "?"
        else:
            faith = "yes" if r["faithful"] else "no"
        print(
            f"{r['item']['id']:<46} {hit:<4} "
            f"{_fmt_float(r['recall_at_k']):<5} {_fmt_float(r['mrr']):<5} "
            f"{_fmt_float(r['ndcg']):<5} {cite:<5} {faith:<6}"
        )
    print("-" * len(header))
    print(
        f"means (positives, n={s['n_positive']}): "
        f"hit@{TOP_K}={_fmt_float(s['hit_at_k'])} "
        f"recall@{TOP_K}={_fmt_float(s['recall_at_k'])} "
        f"MRR={_fmt_float(s['mrr'])} "
        f"nDCG@{TOP_K}={_fmt_float(s['ndcg_at_k'])}"
    )
    print(
        f"citation validity (all, n={s['n_total']}): "
        f"{_fmt_float(s['citation_validity'])}"
    )
    if s["faith_judged"]:
        print(f"faithfulness (judged {s['faith_judged']}/{s['n_positive']}): "
              f"{_fmt_float(s['faithfulness'])}")
    else:
        print("faithfulness: not judged (judge unavailable or no sufficient answers)")
    if s["errors"]:
        print(f"errors: {s['errors']} — see report")


def _write_report(results: list[dict], s: dict) -> None:
    provider = os.environ.get("LLM_PROVIDER", "<unset>")
    model = os.environ.get("LLM_MODEL", "<default>")
    judge_provider = os.environ.get("LLM_JUDGE_PROVIDER") or provider
    judge_model = os.environ.get("LLM_JUDGE_MODEL", "<default>")

    lines: list[str] = [
        "# Wave 1.5 — Mini-eval report",
        "",
        "- Corpus: AAPL FY2024 10-K (period `2024-09-28`)",
        f"- Items: {s['n_total']} "
        f"({s['n_positive']} positive + {s['n_insufficient']} insufficient-context)",
        f"- `top_k = {TOP_K}`, ground-truth probe `K_max = {PROBE_K}`",
        f"- LLM provider: `{provider}` / model: `{model}`",
        f"- Judge provider: `{judge_provider}` / model: `{judge_model}`",
        "- Embedding: NVIDIA NeMo Retriever `nv-embedqa-e5-v5`",
        "",
        "## Headline metrics (means over positive items unless noted)",
        "",
        f"- **hit@{TOP_K}**: {_fmt_float(s['hit_at_k'])}",
        f"- **recall@{TOP_K}**: {_fmt_float(s['recall_at_k'])}",
        f"- **MRR**: {_fmt_float(s['mrr'])}",
        f"- **nDCG@{TOP_K}**: {_fmt_float(s['ndcg_at_k'])}",
        f"- **citation validity** (all items, structural): "
        f"{_fmt_float(s['citation_validity'])}",
        f"- **faithfulness** (LLM-judge over {s['faith_judged']}/"
        f"{s['n_positive']} positive answers): {_fmt_float(s['faithfulness'])}",
        "",
        "Ground-truth relevance is approximated by OR-of-AND keyword groups, so "
        "`recall@k` and `nDCG@k` use a local denominator (relevants found within "
        f"top-{PROBE_K}). MRR is the reciprocal rank of the first relevant chunk "
        f"in that top-{PROBE_K} probe; 0 when nothing relevant surfaces. "
        "Citation validity is structural: positive items must cite a chunk that "
        'matches the relevance predicate; negative items must declare exactly '
        '`"Insufficient context"` with no citations.',
        "",
        "Caveats: n=7 over a single 10-K — these numbers are illustrative, not a "
        "recall benchmark. Wave 2's harness widens to 30–50 curated items with "
        "category coverage and stability checks.",
        "",
        "## Per-item results",
        "",
        f"| id | hit@{TOP_K} | recall@{TOP_K} | MRR | nDCG@{TOP_K} | citation valid | "
        f"faithful | total relevant in top-{PROBE_K} |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        hit = "—" if r["hit_at_k"] is None else ("yes" if r["hit_at_k"] else "no")
        cite = "yes" if r["citation_valid"] else "no"
        if r["faithful"] is None:
            faith = "—" if not r["item"]["relevance"] else "not judged"
        else:
            faith = "yes" if r["faithful"] else "no"
        lines.append(
            f"| `{r['item']['id']}` | {hit} | {_fmt_float(r['recall_at_k'])} "
            f"| {_fmt_float(r['mrr'])} | {_fmt_float(r['ndcg'])} | {cite} | {faith} "
            f"| {r['total_relevant_probe']} |"
        )

    lines += ["", "## Answers + judge reasons", ""]
    for r in results:
        item = r["item"]
        lines += [
            f"### `{item['id']}`",
            "",
            f"**Question.** {item['question']}",
            "",
            f"**Expected.** {item['notes']}",
            "",
            f"**Retrieved top-{TOP_K} chunk_indexes.** {r['retrieved_top_k_indexes']}",
            "",
            f"**Relevant ranks in top-{PROBE_K}.** {r['relevant_ranks']}",
            "",
        ]
        if r["error"]:
            lines += [f"**Error.** `{r['error']}`", ""]
        else:
            lines += [
                f"**Answer.** {r['answer_text']}",
                "",
                f"**Cited chunk_indexes.** {r['cited_indexes']}",
                "",
            ]
        if r["faithful"] is not None or r["faith_reason"]:
            lines += [
                f"**Judge faithfulness.** {r['faithful']} — {r['faith_reason']}",
                "",
            ]
        lines += ["**Human pass/fail.** _TBD — fill in after review._", ""]

    lines += [
        "## Theory ↔ Practice",
        "",
        "RAGAS (Es 2023) separates retrieval and generation axes. This mini-eval "
        "covers retrieval with hit@k / recall@k / MRR / nDCG@k under an "
        "approximate keyword ground truth, and generation with a structural "
        "citation check plus an LLM-judge faithfulness pass. The single-judge "
        "setup inherits bias risks discussed in Zheng 2023; Wave 2 will add a "
        "second-judge sanity check and stability across re-runs. ragas itself "
        "is intentionally not wired here — it is a Wave-2 dependency choice "
        "alongside the bigger 30–50 item set.",
        "",
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines))
    print(f"\nWrote {REPORT_PATH}")


def run() -> None:
    _check_env()
    results = [_run_item(item) for item in ITEMS]
    s = _summary(results)
    _print_table(results, s)
    _write_report(results, s)


if __name__ == "__main__":
    run()
