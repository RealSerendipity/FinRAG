"""Embedding provider — NVIDIA NeMo Retriever.

Public surface
--------------
- `embed(texts, *, input_type)` — returns list of float vectors, one per input text
"""

from __future__ import annotations

from . import config
from .clients import nvidia as nvidia_client


def embed(texts: list[str], *, input_type: str = "passage") -> list[list[float]]:
    """Return one embedding vector per input text.

    Uses NVIDIA NeMo Retriever via the OpenAI-compatible endpoint.
    input_type: "passage" for indexing chunks, "query" for search queries.
    """
    if not texts:
        return []
    api_key = config.api_key("nvidia")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")
    return nvidia_client.create_embeddings(
        texts,
        api_key=api_key,
        base_url=config.nvidia_base_url(),
        model=config.embedding_model(),
        input_type=input_type,
    )
