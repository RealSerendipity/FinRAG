"""Embedding providers — NVIDIA NeMo Retriever (primary) + Gemini (Wave 3f).

Single-file `if/elif` dispatch by provider, same philosophy as src/llm.py. The
production index is NVIDIA `nv-embedqa-e5-v5` (1024-d, matches the chunks column);
Gemini was added for the Wave 3f provider comparison. Voyage / Cohere stay
unimplemented until their keys exist (rule §3.1 — no abstraction before the
second real implementation, no stubs for providers we cannot call).

Public surface
--------------
- `embed(texts, *, input_type, provider)` — list of float vectors, one per text
"""

from __future__ import annotations

from . import config
from .clients import gemini as gemini_client
from .clients import nvidia as nvidia_client

# Default Gemini embedding model (provider-specific; not the NVIDIA EMBEDDING_MODEL).
_GEMINI_EMBED_MODEL = "gemini-embedding-001"
_GEMINI_TASK = {"passage": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


def embed(
    texts: list[str], *, input_type: str = "passage", provider: str | None = None
) -> list[list[float]]:
    """Return one embedding vector per input text.

    input_type: "passage" for indexing chunks, "query" for search queries.
    provider: defaults to EMBEDDING_PROVIDER env (nvidia). "gemini" also wired.
    """
    if not texts:
        return []
    provider = (provider or config.embedding_provider()).lower()

    if provider == "nvidia":
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

    if provider == "gemini":
        api_key = config.api_key("gemini")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        if input_type not in _GEMINI_TASK:
            raise ValueError(f"input_type must be one of {tuple(_GEMINI_TASK)}")
        return gemini_client.create_embeddings(
            texts,
            api_key=api_key,
            model=_GEMINI_EMBED_MODEL,
            task_type=_GEMINI_TASK[input_type],
        )

    raise ValueError(
        f"Unsupported EMBEDDING_PROVIDER {provider!r}; wired: nvidia, gemini "
        "(voyage/cohere require their API keys — not yet implemented)"
    )
