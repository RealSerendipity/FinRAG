"""Embedding provider — Wave 1a: NVIDIA NeMo Retriever only.

Public surface
--------------
- `embed(texts)` — returns list of float vectors, one per input text
"""

from __future__ import annotations

from openai import OpenAI

from . import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.api_key("nvidia"),
            base_url=config.nvidia_base_url(),
        )
    return _client


def embed(texts: list[str], *, input_type: str = "passage") -> list[list[float]]:
    """Return one embedding vector per input text.

    Uses NVIDIA NeMo Retriever via the OpenAI-compatible endpoint.
    input_type: "passage" for indexing chunks, "query" for search queries.
    """
    if not texts:
        return []

    client = _get_client()
    model = config.embedding_model()
    resp = client.embeddings.create(
        input=texts,
        model=model,
        extra_body={"input_type": input_type},
    )
    # Sort by index to guarantee order matches input.
    items = sorted(resp.data, key=lambda e: e.index)
    return [item.embedding for item in items]
