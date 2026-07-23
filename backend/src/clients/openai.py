"""OpenAI LLM SDK raw call (chat completions)."""
from __future__ import annotations


def complete(
    messages: list[dict],
    model: str,
    *,
    api_key: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
):
    """Send a chat.completions.create request; return the raw SDK response."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    payload = list(messages)
    if system:
        payload = [{"role": "system", "content": system}, *payload]
    return client.chat.completions.create(
        model=model,
        messages=payload,
        temperature=temperature,
        max_tokens=max_tokens,
    )
