"""Wave 3d — cross-encoder reranking (NVIDIA NeMo Retriever) over a candidate pool.

Hypothesis: reranking a top-50 candidate pool down to top-10 with a cross-encoder
lifts MRR and nDCG@10 (relevant chunks move up) without changing the candidate
generator; recall@10 may be ~flat (same set, reordered) while recall@5 / MRR rise.

Candidate generation is batched (one LATERAL pgvector query + one FTS query); the
reranker is then called once per item over the candidate content.

Usage: uv run python experiments/wave3_d_rerank.py
"""

from __future__ import annotations

from pathlib import Path

import _ablation as ab

from src.rerank import rerank

REPORT = Path(__file__).parent.parent / "eval" / "reports" / "wave_3d.md"
TOP_K = 10
CANDIDATES = 50


def main() -> None:
    items = ab.load_items(positive_only=True)
    tickers = sorted({it["ticker"] for it in items})
    print(f"loading content for {tickers}; batched dense + FTS...", flush=True)
    content = ab.load_content(tickers)
    dense = ab.dense_rank_all(items, k=CANDIDATES)
    fts = ab.fts_rank_all(items, k=CANDIDATES)
    totals = ab.totals_from_content(items, content)

    def dense_fn(it):
        return ab.chunks_from_ids(dense[it["id"]], content, TOP_K)

    def hybrid_fn(it):
        return ab.chunks_from_ids(ab.rrf_ids([dense[it["id"]], fts[it["id"]]], pool=CANDIDATES),
                                  content, TOP_K)

    def dense_rr_fn(it):
        return rerank(it["question"], ab.chunks_from_ids(dense[it["id"]], content), top_k=TOP_K)

    def hybrid_rr_fn(it):
        fused = ab.rrf_ids([dense[it["id"]], fts[it["id"]]], pool=CANDIDATES)
        return rerank(it["question"], ab.chunks_from_ids(fused, content), top_k=TOP_K)

    specs = [("dense", dense_fn), ("dense+rerank", dense_rr_fn),
             ("hybrid", hybrid_fn), ("hybrid+rerank", hybrid_rr_fn)]
    results, variants = {}, []
    for name, fn in specs:
        print(f"running {name}...", flush=True)
        res = ab.eval_variant(fn, items, totals)
        results[name], _ = res, variants.append((name, res["agg"]))

    hy, hyr = results["hybrid"]["agg"], results["hybrid+rerank"]["agg"]
    lines = [
        "# Wave 3d — Cross-encoder reranking (NVIDIA NeMo Retriever)",
        "",
        "**Hypothesis.** Reranking a top-50 pool down to top-10 lifts MRR / nDCG@10 "
        "without changing the candidate generator; recall@10 ~flat, recall@5 / MRR up.",
        "",
        "- Model: `nvidia/rerank-qa-mistral-4b` via the NeMo Retriever reranking "
        "endpoint. The plan named `nv-rerankqa-mistral-4b-v3`, which is not "
        "provisioned for this account; the served `rerank-qa-mistral-4b` is used.",
        f"- Candidate pool = {CANDIDATES} → reranked to top_k = {TOP_K}.",
        f"- Corpus: {', '.join(tickers)} 10-Ks ({len(content)} chunks); "
        f"{len(items)} positive eval items.",
        "- Recall denominator = true count of relevant chunks in the filtered corpus.",
        "",
        "## Variant comparison (means over positive items)",
        "",
        *ab.comparison_table(variants),
        "",
        f"**Headline.** hybrid → hybrid+rerank: {ab.delta_line(hy, hyr, 'mrr')}; "
        f"{ab.delta_line(hy, hyr, 'ndcg@10')}; {ab.delta_line(hy, hyr, 'recall@5')}.",
        "",
        "## Theory ↔ Practice",
        "",
        "A bi-encoder (the embedding model) encodes query and passage separately, "
        "so it cannot model token-level interaction; a cross-encoder reranker reads "
        "the (query, passage) pair jointly and scores relevance directly. The cost "
        "is latency, so the standard pattern is retrieve-cheap-then-rerank: pull a "
        "wide candidate pool with the bi-encoder/RRF, then spend the cross-encoder "
        "only on those candidates. A good reranker's signature is rank quality up "
        "(MRR / nDCG / recall@5) with recall@10 roughly preserved, since it reorders "
        "rather than expands the candidate set.",
    ]
    ab.write_report(REPORT, lines)


if __name__ == "__main__":
    main()
