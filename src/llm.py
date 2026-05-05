"""Three-provider LLM dispatch — Gemini (primary), Anthropic, OpenAI.

Single-file `if/elif` dispatch by design. Each provider branch owns its own
SDK import (lazy), message-format conversion, and usage extraction. We do not
unify behind an abstract base class — the differences (system prompt handling,
cache control, tool schemas) are easier to read inline than to abstract away.

Public surface
--------------
- `chat(messages, *, provider=None, model=None, system=None, ...)` -> LLMResponse
- `LLMResponse` dataclass with `text`, `usage`, `provider`, `model`, `raw`

Wave 0 implements basic single-turn chat. Caching, tool use, and streaming are
left for later waves; entry points are noted in comments where they will land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config


@dataclass
class LLMResponse:
    text: str
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    raw: Any = None


Message = dict[str, str]  # {"role": "user"|"assistant", "content": "..."}


def chat(
    messages: list[Message],
    *,
    provider: str | None = None,
    model: str | None = None,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> LLMResponse:
    """Send a chat completion request.

    `messages` uses OpenAI-style `[{"role": ..., "content": ...}]`. `system`
    is passed separately (each provider has its own native slot for it).
    """
    provider = (provider or config.llm_provider()).lower()
    if provider not in ("gemini", "anthropic", "openai"):
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")
    model = model or config.llm_model(provider)

    if provider == "gemini":
        return _chat_gemini(messages, model, system, temperature, max_tokens)
    if provider == "anthropic":
        return _chat_anthropic(messages, model, system, temperature, max_tokens)
    return _chat_openai(messages, model, system, temperature, max_tokens)


# --------------------------------------------------------------------------- #
# Gemini (primary)
# --------------------------------------------------------------------------- #
def _chat_gemini(
    messages: list[Message],
    model: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    from google import genai
    from google.genai import types

    api_key = config.api_key("gemini")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    contents = [
        {
            # Gemini uses "model" instead of "assistant".
            "role": "model" if m["role"] == "assistant" else m["role"],
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]

    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    # Wave 5 will add explicit context caching via client.caches.create(...).
    resp = client.models.generate_content(model=model, contents=contents, config=cfg)

    meta = getattr(resp, "usage_metadata", None)
    usage = (
        {
            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
            "total_tokens": getattr(meta, "total_token_count", 0) or 0,
        }
        if meta
        else {}
    )
    return LLMResponse(
        text=(resp.text or "").strip(),
        usage=usage,
        provider="gemini",
        model=model,
        raw=resp,
    )


# --------------------------------------------------------------------------- #
# Anthropic (backup; Wave 5 uses this for prompt-caching demo)
# --------------------------------------------------------------------------- #
def _chat_anthropic(
    messages: list[Message],
    model: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    from anthropic import Anthropic

    api_key = config.api_key("anthropic")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)
    # Wave 5 will add cache_control={"type": "ephemeral"} on system + tool blocks.
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
    }
    return LLMResponse(text=text.strip(), usage=usage, provider="anthropic", model=model, raw=resp)


# --------------------------------------------------------------------------- #
# OpenAI (backup)
# --------------------------------------------------------------------------- #
def _chat_openai(
    messages: list[Message],
    model: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    from openai import OpenAI

    api_key = config.api_key("openai")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)
    payload = list(messages)
    if system:
        payload = [{"role": "system", "content": system}, *payload]

    resp = client.chat.completions.create(
        model=model,
        messages=payload,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    choice = resp.choices[0]
    usage = {
        "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
        "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
        "total_tokens": resp.usage.total_tokens if resp.usage else 0,
    }
    return LLMResponse(
        text=(choice.message.content or "").strip(),
        usage=usage,
        provider="openai",
        model=model,
        raw=resp,
    )
