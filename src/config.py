"""Environment-driven configuration.

Single source of truth for runtime knobs. We load `.env` once at import time
and expose plain functions; no settings object — keep it boring.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ----- LLM -----
DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_LLM_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1-mini",
}
DEFAULT_JUDGE_MODELS = {
    "gemini": "gemini-2.5-flash-lite",
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4.1-nano",
}


def llm_provider() -> str:
    return os.environ.get("LLM_PROVIDER", DEFAULT_LLM_PROVIDER).lower()


def llm_model(provider: str | None = None) -> str:
    provider = provider or llm_provider()
    return os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODELS[provider]


def judge_provider() -> str:
    return os.environ.get("LLM_JUDGE_PROVIDER", llm_provider()).lower()


def judge_model(provider: str | None = None) -> str:
    provider = provider or judge_provider()
    return os.environ.get("LLM_JUDGE_MODEL") or DEFAULT_JUDGE_MODELS[provider]


def api_key(provider: str) -> str | None:
    return os.environ.get(
        {
            "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }[provider]
    )
