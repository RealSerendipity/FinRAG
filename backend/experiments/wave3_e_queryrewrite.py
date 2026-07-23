"""Wave 3e — query rewriting (multi-query / HyDE) for under-specified queries.

To simulate under-specification we drop the period filter, forcing the retriever
to disambiguate across both fiscal years from the query text alone, then compare
a raw-query dense search against multi-query fusion and HyDE.

Hypothesis: on under-specified queries, multi-query fusion and/or HyDE lift
recall@10 over a single raw-query dense search; if neither helps, the raw queries
already carry enough signal and rewriting is unnecessary cost.

Usage: uv run python experiments/wave3_e_queryrewrite.py [--limit N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _ablation as ab

from src.query_rewrite import hyde, multi_query

REPORT = Path(__file__).parent.parent / "eval" / "reports" / "wave_3e.md"
TOP_K = 10
POOL = 20  # per-subquery depth before fusion


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    items = ab.load_items(positive_only=True)
    if args.limit:
        items = items[: args.limit]
    tickers = sorted({it["ticker"] for it in items})
    print(f"loading content for {tickers}...", flush=True)
    content = ab.load_content(tickers)
    # Under-specified condition: NO period filter anywhere.
    totals = ab.totals_from_content(items, content, ignore_period=True)

    print("baseline (raw dense, no period filter)...", flush=True)
    base_dense = ab.dense_rank_all(items, k=TOP_K, ignore_period=True)

    print("generating multi-query paraphrases (LLM)...", flush=True)
    variants_by_item = {it["id"]: multi_query(it["question"], n=3) for it in items}
    sub_items = [
        {**it, "id": f"{it['id']}#{j}", "question": v}
        for it in items
        for j, v in enumerate(variants_by_item[it["id"]])
    ]
    sub_dense = ab.dense_rank_all(sub_items, k=POOL, ignore_period=True)

    print("generating HyDE passages (LLM)...", flush=True)
    hyde_items = [{**it, "question": hyde(it["question"])} for it in items]
    hyde_dense = ab.dense_rank_all(hyde_items, k=TOP_K, ignore_period=True)

    def base_fn(it):
        return ab.chunks_from_ids(base_dense[it["id"]], content, TOP_K)

    def multi_fn(it):
        lists = [sub_dense[f"{it['id']}#{j}"] for j in range(len(variants_by_item[it["id"]]))]
        return ab.chunks_from_ids(ab.rrf_ids(lists, pool=POOL), content, TOP_K)

    def hyde_fn(it):
        return ab.chunks_from_ids(hyde_dense[it["id"]], content, TOP_K)

    results, variants = {}, []
    for name, fn in [("dense (raw)", base_fn), ("multi-query", multi_fn), ("hyde", hyde_fn)]:
        res = ab.eval_variant(fn, items, totals)
        results[name], _ = res, variants.append((name, res["agg"]))

    base = results["dense (raw)"]["agg"]
    lines = [
        "# Wave 3e — Query rewriting (multi-query / HyDE) on under-specified queries",
        "",
        "**Hypothesis.** With the period filter dropped (under-specified), "
        "multi-query fusion and/or HyDE lift recall@10 vs a single raw-query dense "
        "search; if neither helps, the raw queries already carry enough signal.",
        "",
        "- Under-specified condition: ticker filter only, NO period filter "
        "(retriever must disambiguate FY2024 vs FY2025 from text alone).",
        f"- {len(items)} positive items; `top_k = {TOP_K}`, multi-query pool = "
        f"{POOL}/subquery, RRF k = 60.",
        "- Rewrite LLM: NVIDIA NIM (`meta/llama-3.3-70b-instruct`).",
        "- Recall denominator = relevant chunks across the whole-ticker corpus.",
        "",
        "## Variant comparison (means over positive items)",
        "",
        *ab.comparison_table(variants),
        "",
        f"**Headline.** raw → multi-query: {ab.delta_line(base, results['multi-query']['agg'])}; "
        f"raw → HyDE: {ab.delta_line(base, results['hyde']['agg'])}.",
        "",
        "## Theory ↔ Practice",
        "",
        "Multi-query (RAG-Fusion) hedges against a single bad phrasing by issuing "
        "several paraphrases and fusing their rankings with RRF; HyDE (Gao 2022) "
        "instead embeds a hypothetical answer, on the bet that an answer-shaped "
        "passage sits nearer the real answer chunks in embedding space than the "
        "question does. Both trade extra LLM calls (and, for multi-query, extra "
        "retrievals) for recall on vague inputs. Dropping the period filter is the "
        "honest stress test: with the filter on, metadata already does the "
        "disambiguation these rewrites are meant to provide — which is why the "
        "shipped default keeps rewriting OFF and relies on metadata + rerank.",
    ]
    ab.write_report(REPORT, lines)


if __name__ == "__main__":
    main()
