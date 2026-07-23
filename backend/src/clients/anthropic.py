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
        # Wave 5B: cache the (stable, large) system prompt as an ephemeral block so
        # repeat requests read it from cache instead of re-billing input tokens.
        # Usage comes back with cache_creation / cache_read counts (see llm.py).
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    if thinking:
        kwargs["thinking"] = thinking
    return client.messages.create(**kwargs)
