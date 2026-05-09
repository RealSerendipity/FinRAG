"""Embedding provider — NVIDIA NeMo Retriever.

Public surface
--------------
- `embed(texts, *, input_type)` — returns list of float vectors, one per input text
"""

from __future__ import annotations

from src import config
from src.clients import nvidia as nvidia_client


def embed(texts: list[str], *, input_type: str = "passage") -> list[list[float]]:
    """Return one embedding vector per input text.

    Uses NVIDIA NeMo Retriever via the OpenAI-compatible endpoint.
    input_type: "passage" for indexing chunks, "query" for search queries.
    """
    if not texts:
        return []
    return nvidia_client.create_embeddings(
        texts,
        api_key=config.api_key("nvidia"),
        base_url=config.nvidia_base_url(),
        model=config.embedding_model(),
        input_type=input_type,
    )
