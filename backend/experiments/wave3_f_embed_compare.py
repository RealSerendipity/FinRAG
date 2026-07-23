"""Wave 3f — embedding provider comparison: NVIDIA vs Gemini (vs Voyage/Cohere N/A).

Hypothesis: the embedding model is a meaningful retrieval lever — swapping NVIDIA
`nv-embedqa-e5-v5` (1024-d) for Gemini `gemini-embedding-001` (3072-d) shifts
recall@10 by more than eval noise (±0.02). If the two are within noise, embedding
choice is not where Wave 3 effort should go.

Providers have different output dims, so ranking is done in numpy (cosine), not in
pgvector (whose column is fixed at 1024-d). Voyage / Cohere are listed as data
points but not run — their API keys are absent in this environment.

Usage: uv run python experiments/wave3_f_embed_compare.py
"""

from __future__ import annotations

import time
from pathlib import Path

import _ablation as ab
import numpy as np

from src.embed import embed

REPORT = Path(__file__).parent.parent / "eval" / "reports" / "wave_3f.md"
TOP_K = 10
EMBED_BATCH = 32
PROVIDERS = ("nvidia", "gemini")
NOT_RUN = ("voyage", "cohere")


def _embed_batch(texts: list[str], provider: str, input_type: str) -> list[list[float]]:
    """Embed one batch, retrying on provider rate limits (Gemini free tier = ~100/min)."""
    for attempt in range(8):
        try:
            return embed(texts, input_type=input_type, provider=provider)
        except Exception as exc:
            msg = str(exc).lower()
            if ("429" in msg or "resource_exhausted" in msg or "quota" in msg) and attempt < 7:
                print(f"    rate-limited, backing off 30s (attempt {attempt})...", flush=True)
                time.sleep(30)
                continue
            raise
    raise RuntimeError("unreachable")


def _embed_all(texts: list[str], provider: str, input_type: str) -> np.ndarray:
    vecs: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        vecs.extend(_embed_batch(texts[i : i + EMBED_BATCH], provider, input_type))
    arr = np.asarray(vecs, dtype=float)
    return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12)


def evaluate(provider: str, items: list[dict], content: dict[int, dict],
             totals: dict[str, int]) -> dict:
    ids = list(content)
    print(f"  [{provider}] embedding {len(ids)} chunks...", flush=True)
    chunk_mat = _embed_all([content[i]["content"] for i in ids], provider, "passage")
    print(f"  [{provider}] embedding {len(items)} queries...", flush=True)
    qmat = _embed_all([it["question"] for it in items], provider, "query")
    qvec = {it["id"]: qmat[j] for j, it in enumerate(items)}

    def rank(it):
        yr = ab._year(it.get("period"))
        cand = [
            (i, cid) for i, cid in enumerate(ids)
            if content[cid]["ticker"] == it["ticker"]
            and (yr is None or content[cid]["year"] == yr)
        ]
        sims = [(float(qvec[it["id"]] @ chunk_mat[i]), cid) for i, cid in cand]
        sims.sort(reverse=True)
        return [content[cid] for _, cid in sims[:TOP_K]]

    return ab.eval_variant(rank, items, totals)


def main() -> None:
    items = ab.load_items(positive_only=True)
    tickers = sorted({it["ticker"] for it in items})
    print(f"loading content for {tickers}...", flush=True)
    content = ab.load_content(tickers)
    totals = ab.totals_from_content(items, content)

    results, variants = {}, []
    for provider in PROVIDERS:
        res = evaluate(provider, items, content, totals)
        results[provider], _ = res, variants.append((provider, res["agg"]))

    nv, gm = results["nvidia"]["agg"], results["gemini"]["agg"]
    lines = [
        "# Wave 3f — Embedding provider comparison (NVIDIA vs Gemini)",
        "",
        "**Hypothesis.** Embedding choice shifts recall@10 by more than eval noise "
        "(±0.02); if within noise, it is not where Wave 3 effort belongs.",
        "",
        f"- Corpus: {', '.join(tickers)} 10-Ks ({len(content)} chunks); "
        f"{len(items)} positive items; dense (cosine) ranking in numpy.",
        "- NVIDIA `nv-embedqa-e5-v5` (1024-d) vs Gemini `gemini-embedding-001` (3072-d).",
        "- Recall denominator = true count of relevant chunks in the filtered corpus "
        "(same for both providers — content is identical).",
        f"- Not run: {', '.join(NOT_RUN)} — API keys absent in this environment.",
        "",
        "## Variant comparison (means over positive items)",
        "",
        *ab.comparison_table(variants),
        "",
        "| voyage | — | — | — | — | — | — |",
        "| cohere | — | — | — | — | — | — |",
        "",
        f"**Headline.** NVIDIA → Gemini: {ab.delta_line(nv, gm, 'recall@10')}; "
        f"{ab.delta_line(nv, gm, 'mrr')}; {ab.delta_line(nv, gm, 'ndcg@10')}.",
        "",
        "## Theory ↔ Practice",
        "",
        "Embedding models differ in training data, dimensionality, and similarity "
        "geometry, so they are not interchangeable — but on a narrow domain a "
        "domain-tuned retrieval embedding can match or beat a larger general one. "
        "NVIDIA `nv-embedqa-e5-v5` is purpose-built for retrieval QA at 1024-d; "
        "Gemini `gemini-embedding-001` is a larger general model at 3072-d (3x the "
        "storage and distance-compute cost). The comparison is run with identical "
        "chunks and queries so any delta is attributable to the embedding alone; a "
        "within-noise result argues for keeping the cheaper, index-matched NVIDIA "
        "embedding rather than paying 3x for Gemini vectors.",
    ]
    ab.write_report(REPORT, lines)


if __name__ == "__main__":
    main()
