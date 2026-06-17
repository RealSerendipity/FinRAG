"""Wave 2 eval harness — full run over eval/questions.jsonl.

Usage
-----
    uv run python eval/run_eval.py [--limit N] [--out eval/reports/wave_2.md]

Per item: probe retrieval (top-50) → retrieval metrics (hit/recall/MRR/nDCG at
k=5,10 + doc coverage) → answer via the RAG pipeline (top_k=5) → structural
citation validity → LLM-judge faithfulness / answer-relevancy / correctness.

Prerequisites: AAPL FY2024 + FY2025 10-Ks ingested; `.env` configured
(`LLM_PROVIDER`, `LLM_JUDGE_PROVIDER`, `NVIDIA_API_KEY`, `DATABASE_URL`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval import metrics  # noqa: E402
from src import db  # noqa: E402
from src.rag import ask  # noqa: E402
from src.retrieve import retrieve  # noqa: E402

QUESTIONS_PATH = Path(__file__).parent / "questions.jsonl"
DEFAULT_REPORT = Path(__file__).parent / "reports" / "wave_2.md"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "answer_v1.1.txt"

ANSWER_TOP_K = 5  # context size for the RAG answer (Wave 1.5 parity)
PROBE_K = 50  # retrieval probe depth used as the local ground-truth denominator
REPORT_KS = (5, 10)  # k values reported for recall / nDCG
CATEGORIES = ("numeric", "table", "cross-document", "reasoning", "consistency")

INSUFFICIENT_TEXT = "insufficient context"


def load_questions(path: Path) -> list[dict]:
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [it["id"] for it in items]
    if len(ids) != len(set(ids)):
        sys.exit("questions.jsonl contains duplicate ids")
    return items


def check_env() -> None:
    required = ("DATABASE_URL", "NVIDIA_API_KEY", "LLM_PROVIDER")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        sys.exit(
            f"Missing required env vars: {missing}. Configure .env and ingest "
            "AAPL FY2024/FY2025 10-Ks first."
        )


def chunk_accession_map() -> dict[int, str]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT c.id, d.accession FROM chunks c JOIN documents d ON c.document_id = d.id"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def run_item(item: dict, acc_by_chunk: dict[int, str]) -> dict:
    probe = retrieve(
        item["question"],
        ticker=item["ticker"],
        period=item["period"],
        top_k=PROBE_K,
    )
    contents = [c["content"] for c in probe]
    probe_accessions = [acc_by_chunk.get(c["id"], "") for c in probe]
    id_to_content = {c["id"]: c["content"] for c in probe}
    top_ids = {c["id"] for c in probe[:ANSWER_TOP_K]}

    groups = item["relevance"]
    rel_ranks = metrics.relevant_ranks(contents, groups)
    total_rel = len(rel_ranks)

    retr: dict[str, float | bool | None] = {}
    if groups:
        for k in REPORT_KS:
            retr[f"hit@{k}"] = metrics.hit_at_k(rel_ranks, k)
            retr[f"recall@{k}"] = metrics.recall_at_k(rel_ranks, k, total_rel)
            retr[f"ndcg@{k}"] = metrics.ndcg_at_k(rel_ranks, k, total_rel)
        retr["mrr"] = metrics.mrr(rel_ranks)
        retr["doc_cov@10"] = metrics.doc_coverage_at_k(
            probe_accessions, item["expected_accessions"], 10
        )
    else:
        for k in REPORT_KS:
            retr[f"hit@{k}"] = retr[f"recall@{k}"] = retr[f"ndcg@{k}"] = None
        retr["mrr"] = None
        retr["doc_cov@10"] = None

    answer = None
    error = None
    try:
        answer = ask(
            item["question"],
            ticker=item["ticker"],
            period=item["period"],
            top_k=ANSWER_TOP_K,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    is_sufficient = answer.is_sufficient if answer else False
    answer_text = answer.text if answer else ""
    cited_ids = [cit.chunk_id for cit in (answer.citations if answer else [])]

    if groups:
        cited_relevant = any(
            metrics.matches(id_to_content.get(cid, ""), groups)
            for cid in cited_ids
            if cid in top_ids
        )
        citation_valid = is_sufficient and cited_relevant
    else:
        citation_valid = (
            answer is not None
            and not is_sufficient
            and answer_text.strip().lower() == INSUFFICIENT_TEXT
        )

    verdict = {"faithful": None, "relevant": None, "correct": None, "reason": "", "judge": ""}
    if groups and answer is not None and is_sufficient:
        excerpts = [(cid, id_to_content.get(cid, "<missing>")) for cid in cited_ids]
        verdict = metrics.judge_answer(
            item["question"], item["expected_answer"], answer_text, excerpts
        )

    return {
        "item": item,
        **retr,
        "relevant_ranks": rel_ranks,
        "total_relevant_probe": total_rel,
        "answer_text": answer_text,
        "is_sufficient": is_sufficient,
        "cited_ids": cited_ids,
        "citation_valid": citation_valid,
        **{k: verdict[k] for k in ("faithful", "relevant", "correct", "reason", "judge")},
        "error": error,
    }


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _bools(results: list[dict], key: str) -> list[float | None]:
    return [None if r[key] is None else (1.0 if r[key] else 0.0) for r in results]


def summarize(results: list[dict]) -> dict:
    positives = [r for r in results if r["item"]["relevance"]]
    judged = [r for r in positives if r["faithful"] is not None]
    s: dict = {
        "n_total": len(results),
        "n_positive": len(positives),
        "n_insufficient": len(results) - len(positives),
        "n_judged": len(judged),
        "errors": sum(1 for r in results if r["error"]),
    }
    for k in REPORT_KS:
        s[f"hit@{k}"] = metrics.mean(_bools(positives, f"hit@{k}"))
        s[f"recall@{k}"] = metrics.mean([r[f"recall@{k}"] for r in positives])
        s[f"ndcg@{k}"] = metrics.mean([r[f"ndcg@{k}"] for r in positives])
    s["mrr"] = metrics.mean([r["mrr"] for r in positives])
    s["doc_cov@10"] = metrics.mean([r["doc_cov@10"] for r in positives])
    s["citation_validity"] = metrics.mean(_bools(results, "citation_valid"))
    s["faithfulness"] = metrics.mean(_bools(judged, "faithful"))
    s["answer_relevancy"] = metrics.mean(_bools(judged, "relevant"))
    s["correctness"] = metrics.mean(_bools(judged, "correct"))
    return s


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return f"{value:.{digits}f}"


def consistency_pairs(results: list[dict]) -> list[dict]:
    by_id = {r["item"]["id"]: r for r in results}
    pairs = []
    for r in results:
        base_id = r["item"].get("paired_with")
        if not base_id or base_id not in by_id:
            continue
        base = by_id[base_id]
        pairs.append(
            {
                "paraphrase": r["item"]["id"],
                "base": base_id,
                "paraphrase_correct": r["correct"],
                "base_correct": base["correct"],
                "agree": (
                    None
                    if r["correct"] is None or base["correct"] is None
                    else r["correct"] == base["correct"]
                ),
            }
        )
    return pairs


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def write_report(
    results: list[dict], s: dict, by_cat: dict[str, dict], out_path: Path
) -> None:
    prompt_sha = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()[:12]
    provider = os.environ.get("LLM_PROVIDER", "<unset>")
    model = os.environ.get("LLM_MODEL", "<default>")
    judge_provider = os.environ.get("LLM_JUDGE_PROVIDER") or provider
    judge_model = os.environ.get("LLM_JUDGE_MODEL", "<default>")

    lines = [
        "# Wave 2 — Eval harness report (Wave 1 baseline)",
        "",
        "- Corpus: AAPL FY2024 10-K (`0000320193-24-000123`) + AAPL FY2025 10-K "
        "(`0000320193-25-000079`)",
        f"- Items: {s['n_total']} ({s['n_positive']} positive + "
        f"{s['n_insufficient']} insufficient-context), 5 categories",
        f"- `answer top_k = {ANSWER_TOP_K}`, probe `K_max = {PROBE_K}`",
        f"- LLM provider: `{provider}` / model: `{model}`",
        f"- Judge provider: `{judge_provider}` / model: `{judge_model}` "
        f"(fallback: `{'/'.join(metrics.FALLBACK_JUDGE)}`)",
        f"- Prompt: `prompts/answer_v1.1.txt` (sha256 `{prompt_sha}`)",
        "- Embedding: NVIDIA NeMo Retriever `nv-embedqa-e5-v5`",
        "",
        "## Headline metrics (means over positive items unless noted)",
        "",
    ]
    for k in REPORT_KS:
        lines.append(f"- **recall@{k}**: {fmt(s[f'recall@{k}'])}")
    lines += [
        f"- **MRR**: {fmt(s['mrr'])}",
        f"- **nDCG@10**: {fmt(s['ndcg@10'])}",
        f"- **doc coverage@10**: {fmt(s['doc_cov@10'])}",
        f"- **citation validity** (all items, structural): {fmt(s['citation_validity'])}",
        f"- **faithfulness** (judged {s['n_judged']}/{s['n_positive']}): "
        f"{fmt(s['faithfulness'])}",
        f"- **answer relevancy**: {fmt(s['answer_relevancy'])}",
        f"- **correctness vs expected answer**: {fmt(s['correctness'])}",
        "",
        "Relevance ground truth is OR-of-AND keyword groups (Wave 1.5 "
        f"convention), so recall/nDCG use a local denominator (relevants found "
        f"within top-{PROBE_K}). Doc coverage@10 is the fraction of expected "
        "filings present among the top-10 retrieved chunks' documents.",
        "",
        "## Per-category breakdown",
        "",
        "| category | n | hit@5 | recall@10 | MRR | nDCG@10 | cite valid | "
        "faithful | relevant | correct |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cat in CATEGORIES:
        cs = by_cat[cat]
        lines.append(
            f"| {cat} | {cs['n_total']} | {fmt(cs['hit@5'])} | {fmt(cs['recall@10'])} "
            f"| {fmt(cs['mrr'])} | {fmt(cs['ndcg@10'])} | {fmt(cs['citation_validity'])} "
            f"| {fmt(cs['faithfulness'])} | {fmt(cs['answer_relevancy'])} "
            f"| {fmt(cs['correctness'])} |"
        )

    pairs = consistency_pairs(results)
    if pairs:
        lines += [
            "",
            "## Consistency pairs (paraphrase vs base phrasing)",
            "",
            "| paraphrase | base | paraphrase correct | base correct | agree |",
            "|---|---|---|---|---|",
        ]
        for p in pairs:
            lines.append(
                f"| `{p['paraphrase']}` | `{p['base']}` | {fmt(p['paraphrase_correct'])} "
                f"| {fmt(p['base_correct'])} | {fmt(p['agree'])} |"
            )

    lines += [
        "",
        "## Per-item results",
        "",
        "| id | cat | hit@5 | recall@10 | MRR | nDCG@10 | cite | faithful | "
        "correct | rel in probe |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r['item']['id']}` | {r['item']['category']} | {fmt(r['hit@5'])} "
            f"| {fmt(r['recall@10'])} | {fmt(r['mrr'])} | {fmt(r['ndcg@10'])} "
            f"| {fmt(r['citation_valid'])} | {fmt(r['faithful'])} "
            f"| {fmt(r['correct'])} | {r['total_relevant_probe']} |"
        )

    lines += ["", "## Answers + judge reasons", ""]
    for r in results:
        item = r["item"]
        lines += [
            f"### `{item['id']}` ({item['category']})",
            "",
            f"**Question.** {item['question']}",
            "",
            f"**Expected.** {item['expected_answer']}",
            "",
        ]
        if r["error"]:
            lines += [f"**Error.** `{r['error']}`", ""]
        else:
            lines += [
                f"**Answer.** {r['answer_text']}",
                "",
                f"**Cited chunk_ids.** {r['cited_ids']}",
                "",
            ]
        if r["reason"]:
            lines += [
                f"**Judge ({r['judge']}).** faithful={fmt(r['faithful'])}, "
                f"relevant={fmt(r['relevant'])}, correct={fmt(r['correct'])} — "
                f"{r['reason']}",
                "",
            ]

    lines += [
        "## Stability",
        "",
        "_Run this harness twice; headline numbers should agree within ±0.02 "
        "(acceptance gate). Fill in after the rerun:_",
        "",
        "| metric | run 1 | run 2 | |Δ| |",
        "|---|---|---|---|",
        "",
        "## Theory ↔ Practice",
        "",
        "RAGAS (Es 2023) separates retrieval and generation quality; this "
        "harness measures retrieval with recall@k / MRR / nDCG over a keyword "
        "ground truth and generation with a structural citation check plus an "
        "LLM judge for faithfulness, answer relevancy, and correctness. "
        "Following Zheng 2023 on judge bias, the judge is a different provider "
        "than the generator, runs at temperature 0 with a binary rubric, and "
        "the cheap-fallback path reflects the observation that inexpensive "
        "judges suffice for *relative* comparisons between retrieval variants — "
        "the use this harness is built for (Wave 3 ablations).",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"\nWrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N items")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    check_env()
    items = load_questions(QUESTIONS_PATH)
    if args.limit:
        items = items[: args.limit]
    acc_by_chunk = chunk_accession_map()

    results = []
    for i, item in enumerate(items, start=1):
        print(f"[{i}/{len(items)}] {item['id']}", flush=True)
        results.append(run_item(item, acc_by_chunk))

    s = summarize(results)
    by_cat = {
        cat: summarize([r for r in results if r["item"]["category"] == cat])
        for cat in CATEGORIES
    }
    write_report(results, s, by_cat, args.out)

    headline = {
        k: (round(v, 4) if isinstance(v, float) else v)
        for k, v in s.items()
        if k
        in (
            "recall@5",
            "recall@10",
            "mrr",
            "ndcg@10",
            "doc_cov@10",
            "citation_validity",
            "faithfulness",
            "answer_relevancy",
            "correctness",
            "errors",
        )
    }
    print("SUMMARY " + json.dumps(headline))


if __name__ == "__main__":
    main()
