"""Four-provider LLM dispatch — Gemini (primary), Anthropic, OpenAI, NVIDIA NIM.

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
from .clients import anthropic as anthropic_client
from .clients import gemini as gemini_client
from .clients import nvidia as nvidia_client
from .clients import openai as openai_client


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
    if provider not in config._KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. "
            f"Set LLM_PROVIDER to one of: {', '.join(config._KNOWN_PROVIDERS)}"
        )
    model = model or config.llm_model(provider)

    if provider == "gemini":
        return _chat_gemini(messages, model, system, temperature, max_tokens)
    if provider == "anthropic":
        return _chat_anthropic(messages, model, system, temperature, max_tokens)
    if provider == "openai":
        return _chat_openai(messages, model, system, temperature, max_tokens)
    if provider == "nvidia":
        return _chat_nvidia(messages, model, system, temperature, max_tokens)
    raise AssertionError(f"provider {provider!r} passed validation but has no handler")


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
    api_key = config.api_key("gemini")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    resp = gemini_client.generate(
        messages, model,
        api_key=api_key, system=system,
        temperature=temperature, max_tokens=max_tokens,
    )
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
    api_key = config.api_key("anthropic")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    resp = anthropic_client.complete(
        messages, model,
        api_key=api_key, system=system,
        temperature=temperature, max_tokens=max_tokens,
    )
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
    api_key = config.api_key("openai")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    resp = openai_client.complete(
        messages, model,
        api_key=api_key, system=system,
        temperature=temperature, max_tokens=max_tokens,
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


# --------------------------------------------------------------------------- #
# NVIDIA NIM (open-weight via OpenAI-compatible endpoint)
# --------------------------------------------------------------------------- #
def _chat_nvidia(
    messages: list[Message],
    model: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    api_key = config.api_key("nvidia")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")

    resp = nvidia_client.complete(
        messages, model,
        api_key=api_key, base_url=config.nvidia_base_url(),
        system=system, temperature=temperature, max_tokens=max_tokens,
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
        provider="nvidia",
        model=model,
        raw=resp,
    )
