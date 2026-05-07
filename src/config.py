"""Environment-driven configuration.

Single source of truth for runtime knobs. We load `.env` once at import time
and expose plain functions; no settings object — keep it boring.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ----- LLM -----
_KNOWN_PROVIDERS = ("gemini", "anthropic", "openai")

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
    val = os.environ.get("LLM_PROVIDER", "").lower()
    if not val:
        raise RuntimeError(
            "LLM_PROVIDER is not set. Add it to .env: LLM_PROVIDER=gemini|anthropic|openai"
        )
    return val


def llm_model(provider: str | None = None) -> str:
    provider = provider or llm_provider()
    # LLM_MODEL only overrides the active provider; other providers use their defaults.
    if provider == os.environ.get("LLM_PROVIDER", "").lower():
        return os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODELS[provider]
    return DEFAULT_LLM_MODELS[provider]


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
            "nvidia": "NVIDIA_API_KEY",
        }[provider]
    )


# ----- Database -----

def database_url() -> str:
    val = os.environ.get("DATABASE_URL", "")
    if not val:
        raise RuntimeError("DATABASE_URL is not set.")
    return val


# ----- Embedding -----

def embedding_model() -> str:
    return os.environ.get("EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5")


def embedding_dim() -> int:
    return int(os.environ.get("EMBEDDING_DIM", "1024"))


def nvidia_base_url() -> str:
    return os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
