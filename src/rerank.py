"""Reranker dispatch (Wave 3d).

A reranker re-scores retrieved candidates with a cross-encoder that reads the
query and passage together, so it can promote the passage that best answers the
query even when bi-encoder vector distance ranked it lower. Single-provider for
now (NVIDIA); the dispatch shape is here so a second provider stays a one-branch
addition (rule §3.1 — abstraction only when the second implementation lands).

Public surface
--------------
- `rerank(query, chunks, top_k)` — chunks reordered by rerank score, truncated to top_k
"""

from __future__ import annotations

from src import config
from src.clients import nvidia as nvidia_client


def rerank(query: str, chunks: list[dict], *, top_k: int) -> list[dict]:
    """Return chunks reordered by reranker relevance, truncated to top_k.

    Each returned chunk gains a `rerank_score` key. Input chunks must have a
    `content` field. On an empty input the input is returned unchanged.
    """
    if not chunks:
        return chunks
    provider = config.reranker_provider()
    if provider != "nvidia":
        raise ValueError(f"Unsupported RERANKER_PROVIDER {provider!r}; only 'nvidia' is wired")

    api_key = config.api_key("nvidia")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")

    ranked = nvidia_client.rerank(
        query,
        [c["content"] for c in chunks],
        api_key=api_key,
        model=config.reranker_model(),
        url=config.reranker_base_url(),
    )
    out: list[dict] = []
    for idx, score in ranked:
        item = dict(chunks[idx])
        item["rerank_score"] = score
        out.append(item)
    return out[:top_k]
