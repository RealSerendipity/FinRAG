"""NVIDIA NeMo Retriever clients: embedding + chat (OpenAI-compatible) and rerank."""
from __future__ import annotations

import time

import httpx
from openai import OpenAI

_client: OpenAI | None = None
_client_key: tuple[str, str, int, int] | None = None


def _get_client(
    api_key: str,
    base_url: str,
    *,
    timeout_seconds: int = 60,
    max_retries: int = 2,
) -> OpenAI:
    global _client, _client_key
    key = (api_key, base_url, timeout_seconds, max_retries)
    if _client is None or _client_key != key:
        # Cap per-request time — the SDK default is 600s, long enough for a single
        # hung call to stall an entire eval sweep.
        _client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
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


def rerank(
    query: str,
    passages: list[str],
    *,
    api_key: str,
    model: str,
    url: str,
) -> list[tuple[int, float]]:
    """Score passages against query via the NeMo Retriever reranking endpoint.

    This is a dedicated retrieval endpoint (not OpenAI-compatible), so we POST
    directly. Returns (original_index, logit) pairs in the API's ranked order.

    Retries transient transport failures (NVIDIA endpoints occasionally drop the
    TLS connection with an SSL EOF) and 429/5xx with exponential back-off, so a
    blip doesn't crash a whole eval run.
    """
    payload = {
        "model": model,
        "query": {"text": query},
        "passages": [{"text": p} for p in passages],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return [(r["index"], r["logit"]) for r in resp.json()["rankings"]]
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_exc  # unreachable; satisfies type checker


def complete(
    messages: list[dict],
    model: str,
    *,
    api_key: str,
    base_url: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout_seconds: int = 60,
    max_retries: int = 2,
):
    """Call the NVIDIA NIM chat completions endpoint; return the raw SDK response."""
    client = _get_client(
        api_key,
        base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    payload = list(messages)
    if system:
        payload = [{"role": "system", "content": system}, *payload]
    return client.chat.completions.create(
        model=model,
        messages=payload,
        temperature=temperature,
        max_tokens=max_tokens,
    )
