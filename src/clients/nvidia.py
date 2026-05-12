"""NVIDIA NeMo Retriever embedding client (OpenAI-compatible endpoint)."""
from __future__ import annotations

from openai import OpenAI

_client: OpenAI | None = None
_client_key: tuple[str, str] | None = None  # (api_key, base_url)


def _get_client(api_key: str, base_url: str) -> OpenAI:
    global _client, _client_key
    key = (api_key, base_url)
    if _client is None or _client_key != key:
        _client = OpenAI(api_key=api_key, base_url=base_url)
        _client_key = key
    return _client


def create_embeddings(
    texts: list[str],
    *,
    api_key: str,
    base_url: str,
    model: str,
    input_type: str,
) -> list[list[float]]:
    """Call the NVIDIA embedding endpoint; return vectors in input order."""
    client = _get_client(api_key, base_url)
    resp = client.embeddings.create(
        input=texts,
        model=model,
        extra_body={"input_type": input_type},
    )
    items = sorted(resp.data, key=lambda e: e.index)
    return [item.embedding for item in items]


def complete(
    messages: list[dict],
    model: str,
    *,
    api_key: str,
    base_url: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
):
    """Call the NVIDIA NIM chat completions endpoint; return the raw SDK response."""
    client = _get_client(api_key, base_url)
    payload = list(messages)
    if system:
        payload = [{"role": "system", "content": system}, *payload]
    return client.chat.completions.create(
        model=model,
        messages=payload,
        temperature=temperature,
        max_tokens=max_tokens,
    )
