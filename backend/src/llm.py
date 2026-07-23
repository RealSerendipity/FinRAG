"""Four-provider LLM dispatch — NVIDIA NIM (primary: generation + judge);
Gemini, Anthropic, OpenAI as backups.

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

from . import config, cost, obs
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
    if provider not in config.KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. "
            f"Set LLM_PROVIDER to one of: {', '.join(config.KNOWN_PROVIDERS)}"
        )
    model = model or config.llm_model(provider)
    config.validate_provider_model(provider, model)

    # One Langfuse generation span per LLM call; nests under whatever span the
    # request opened. Records token usage and the estimated USD cost (Wave 5B).
    with obs.span(
        f"llm.{provider}",
        as_type="generation",
        model=model,
        model_parameters={"temperature": temperature, "max_tokens": max_tokens},
    ) as sp:
        if provider == "gemini":
            resp = _chat_gemini(messages, model, system, temperature, max_tokens)
        elif provider == "anthropic":
            resp = _chat_anthropic(messages, model, system, temperature, max_tokens)
        elif provider == "openai":
            resp = _chat_openai(messages, model, system, temperature, max_tokens)
        elif provider == "nvidia":
            resp = _chat_nvidia(messages, model, system, temperature, max_tokens)
        else:
            raise AssertionError(f"provider {provider!r} passed validation but has no handler")
        sp.update(
            output=resp.text,
            usage_details=resp.usage,
            cost_details=cost.cost_details(model, resp.usage),
        )
        obs.record_usage(resp.usage, model=model)
        return resp


# --------------------------------------------------------------------------- #
# Gemini (backup)
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


# Models that use adaptive thinking; require temperature=1 at the API level.
_ANTHROPIC_THINKING_MODELS: frozenset[str] = frozenset({"claude-opus-4-7"})


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

    thinking = {"type": "adaptive"} if model in _ANTHROPIC_THINKING_MODELS else None
    resp = anthropic_client.complete(
        messages, model,
        api_key=api_key, system=system,
        temperature=temperature, max_tokens=max_tokens,
        thinking=thinking,
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
# NVIDIA NIM (primary — generation + judge; open-weight via OpenAI-compatible endpoint)
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
        timeout_seconds=config.nvidia_chat_timeout_seconds(),
        max_retries=config.nvidia_chat_max_retries(),
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


def judge_chat(
    messages: list[Message],
    *,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> LLMResponse:
    """Like chat() but uses LLM_JUDGE_PROVIDER / LLM_JUDGE_MODEL from config."""
    provider = config.judge_provider()
    model = config.judge_model(provider)
    return chat(
        messages,
        provider=provider,
        model=model,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
    )
