"""Anthropic SDK raw call."""
from __future__ import annotations

from typing import Any


def complete(
    messages: list[dict],
    model: str,
    *,
    api_key: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    thinking: dict | None = None,
):
    """Send a messages.create request; return the raw SDK response."""
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        # Anthropic requires temperature=1 when extended thinking is enabled.
        "temperature": 1.0 if thinking else temperature,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if thinking:
        kwargs["thinking"] = thinking
    # Wave 5: add cache_control={"type": "ephemeral"} on system + tool blocks here.
    return client.messages.create(**kwargs)
