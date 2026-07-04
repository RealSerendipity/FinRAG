"""Environment-driven configuration."""

from __future__ import annotations

import os
from typing import Annotated, Any

from dotenv import load_dotenv
from pydantic import ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode

load_dotenv()

# ----- LLM -----
# nvidia is the primary provider (generation + judge); the closed providers are
# backups. Order here is cosmetic (used only in error messages); membership, not
# position, drives dispatch. Public: llm.py validates providers against this.
KNOWN_PROVIDERS = ("nvidia", "gemini", "anthropic", "openai")

# ----- Shared limits -----
# MAX_TOP_K: the user-facing top_k cap, shared by the API request model and the
# RAG input model so the two layers cannot drift apart.
# MAX_CANDIDATES: the internal retrieval/rerank candidate-pool cap (RetrieveInput
# accepts pool-sized top_k values when called from rerank/multi-query paths).
MAX_TOP_K = 50
MAX_CANDIDATES = 1000

CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """Validated runtime settings loaded from environment variables and `.env`."""

    model_config = ConfigDict(extra="ignore", case_sensitive=True)

    LLM_PROVIDER: str = ""
    LLM_MODEL: str | None = None
    LLM_JUDGE_PROVIDER: str | None = None
    LLM_JUDGE_MODEL: str | None = None
    GEMINI_MODELS: CommaList = Field(default_factory=list)
    ANTHROPIC_MODELS: CommaList = Field(default_factory=list)
    OPENAI_MODELS: CommaList = Field(default_factory=list)
    NVIDIA_MODELS: CommaList = Field(default_factory=list)
    EMBEDDING_PROVIDER: str = "nvidia"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIM: int | None = Field(default=None, gt=0)
    NVIDIA_BASE_URL: str = ""
    DATABASE_URL: str = ""
    EDGAR_USER_AGENT: str = ""
    GEMINI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    NVIDIA_API_KEY: str | None = None
    VOYAGE_API_KEY: str | None = None
    COHERE_API_KEY: str | None = None
    # ----- Ingestion / retrieval (Wave 3) -----
    CHUNK_STRATEGY: str = "fixed"
    RETRIEVAL_MODE: str = "dense"
    QUERY_REWRITE: str = "none"
    RERANK_ENABLED: bool = False
    RERANK_CANDIDATES: int = Field(default=50, ge=1, le=MAX_CANDIDATES)
    RERANKER_PROVIDER: str = "nvidia"
    RERANKER_MODEL: str = ""
    RERANKER_BASE_URL: str = ""
    # ----- API (Wave 5A) -----
    # API_ROOT_PATH: path prefix when served behind a proxy (e.g. "/finrag" so a
    # Cloudflare Worker can route www.example.com/finrag/* to the app). Empty = root.
    # API_TOKEN: when set, /ask /agent /ingest require `Authorization: Bearer <token>`;
    # unset disables auth (local dev, tests). /health stays open either way.
    API_ROOT_PATH: str = ""
    API_TOKEN: str | None = None
    # MCP_TOKEN: bearer token required by the MCP server's HTTP (streamable-http)
    # transport when exposed as a network service. Unset = no auth (stdio / local only).
    MCP_TOKEN: str | None = None
    # RATE_LIMIT_ENABLED: per-token/IP rate limits on the expensive API routes
    # (/ask /agent /ingest). Off by default (local dev, tests — same convention as
    # API_TOKEN); set 1 for any public exposure so a leaked URL/token cannot burn
    # the free LLM/embedding quotas.
    RATE_LIMIT_ENABLED: bool = False
    # ----- Guardrails (Wave 6) -----
    # GUARDRAILS_ENABLED: run the deterministic input/context/output screens in the
    #   ask/agent path. On by default (a security wave is secure by default); the
    #   screens target injection signatures, not finance content, so benign queries
    #   pass untouched. Set 0 to measure the undefended baseline.
    # NEMOGUARD_ENABLED: additionally consult the NVIDIA NemoGuard content-safety
    #   model on input. Off by default — it costs one extra NIM call per request, so
    #   the inline pipeline stays heuristics-only; the red-team harness opts in.
    GUARDRAILS_ENABLED: bool = True
    NEMOGUARD_ENABLED: bool = False
    NEMOGUARD_CONTENT_SAFETY_MODEL: str = ""
    NEMOGUARD_JAILBREAK_MODEL: str = ""

    @field_validator(
        "GEMINI_MODELS",
        "ANTHROPIC_MODELS",
        "OPENAI_MODELS",
        "NVIDIA_MODELS",
        mode="before",
    )
    @classmethod
    def _parse_comma_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return list(value)

    @field_validator("LLM_PROVIDER", mode="before")
    @classmethod
    def _normalize_required_provider(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    @field_validator("LLM_JUDGE_PROVIDER", mode="before")
    @classmethod
    def _normalize_optional_provider(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None

    @field_validator(
        "LLM_MODEL",
        "LLM_JUDGE_MODEL",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "NVIDIA_API_KEY",
        "API_TOKEN",
        "MCP_TOKEN",
        mode="before",
    )
    @classmethod
    def _strip_empty_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator(
        "DATABASE_URL",
        "EDGAR_USER_AGENT",
        "EMBEDDING_MODEL",
        "NVIDIA_BASE_URL",
        mode="before",
    )
    @classmethod
    def _strip_required_strings(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("API_ROOT_PATH", mode="before")
    @classmethod
    def _normalize_root_path(cls, value: Any) -> str:
        # Normalize to "" or "/prefix" (leading slash, no trailing slash) — the form
        # Starlette expects for root_path behind a path-stripping proxy.
        text = "" if value is None else str(value).strip().strip("/")
        return f"/{text}" if text else ""

    @field_validator("EMBEDDING_DIM", mode="before")
    @classmethod
    def _strip_optional_int(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return value


_MODEL_FIELD_BY_PROVIDER = {
    "gemini": "GEMINI_MODELS",
    "anthropic": "ANTHROPIC_MODELS",
    "openai": "OPENAI_MODELS",
    "nvidia": "NVIDIA_MODELS",
}

_API_KEY_FIELD_BY_PROVIDER = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}


def _env_snapshot() -> tuple[tuple[str, str | None], ...]:
    return tuple((name, os.environ.get(name)) for name in Settings.model_fields)


settings = Settings()
_settings_snapshot = _env_snapshot()


def _get_settings() -> Settings:
    """Return the current settings singleton, refreshing after env changes."""
    global settings, _settings_snapshot
    snapshot = _env_snapshot()
    if snapshot != _settings_snapshot:
        settings = Settings()
        _settings_snapshot = snapshot
    return settings


def llm_provider() -> str:
    val = _get_settings().LLM_PROVIDER
    if not val:
        raise RuntimeError(
            "LLM_PROVIDER is not set. Add it to .env: "
            f"LLM_PROVIDER={'|'.join(KNOWN_PROVIDERS)}"
        )
    return val


def known_models(provider: str) -> frozenset[str] | None:
    """Return the allowed model set for a provider, read from {PROVIDER}_MODELS env var.

    Returns None when the env var is unset — no restriction is applied in that case.
    """
    field_name = _MODEL_FIELD_BY_PROVIDER.get(provider.lower())
    if field_name is None:
        return None
    raw = getattr(_get_settings(), field_name)
    if not raw:
        return None
    return frozenset(raw)


def validate_provider_model(provider: str, model: str) -> None:
    """Raise ValueError if model is not in the provider's allowed set."""
    provider = provider.lower()
    allowed = known_models(provider)
    if allowed is not None and model not in allowed:
        raise ValueError(
            f"Model {model!r} is not valid for provider {provider!r}. "
            f"Allowed models (from {provider.upper()}_MODELS): {sorted(allowed)}. "
            "Update LLM_MODEL / LLM_JUDGE_MODEL in .env."
        )


def _default_model_from_env(provider: str, current_settings: Settings | None = None) -> str:
    provider = provider.lower()
    field_name = _MODEL_FIELD_BY_PROVIDER.get(provider)
    if field_name is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. "
            f"Set LLM_PROVIDER to one of: {', '.join(KNOWN_PROVIDERS)}"
        )
    current_settings = current_settings or _get_settings()
    models = getattr(current_settings, field_name)
    if not models:
        raise RuntimeError(
            f"{field_name} is not set. Add at least one model to .env: "
            f"{field_name}=model-a,model-b"
        )
    return models[0]


def llm_model(provider: str | None = None) -> str:
    provider = provider or llm_provider()
    provider = provider.lower()
    current_settings = _get_settings()
    # LLM_MODEL only overrides the active provider; other providers use their own env list.
    active = current_settings.LLM_PROVIDER
    if provider == active:
        model = current_settings.LLM_MODEL or _default_model_from_env(provider, current_settings)
    else:
        model = _default_model_from_env(provider, current_settings)
    validate_provider_model(provider, model)
    return model


def judge_provider() -> str:
    """Return the provider used for evaluation judging.

    Defaults to LLM_PROVIDER when LLM_JUDGE_PROVIDER is unset. The judge should be
    at least as capable as the generator (and ideally a different model/family) so
    it doesn't rubber-stamp the generator's own outputs. Current setup keeps the
    judge on NVIDIA too (a stronger model), with closed providers as backup.
    """
    return (_get_settings().LLM_JUDGE_PROVIDER or llm_provider()).lower()


def judge_model(provider: str | None = None) -> str:
    """Return the judge model, defaulting to the first env-listed provider model."""
    provider = provider or judge_provider()
    provider = provider.lower()
    current_settings = _get_settings()
    model = current_settings.LLM_JUDGE_MODEL or _default_model_from_env(provider, current_settings)
    validate_provider_model(provider, model)
    return model


def api_key(provider: str) -> str | None:
    return getattr(_get_settings(), _API_KEY_FIELD_BY_PROVIDER[provider])


# ----- Database -----

def database_url() -> str:
    val = _get_settings().DATABASE_URL
    if not val:
        raise RuntimeError("DATABASE_URL is not set.")
    return val


# ----- EDGAR -----

def edgar_user_agent() -> str:
    val = _get_settings().EDGAR_USER_AGENT
    if not val:
        raise RuntimeError(
            "EDGAR_USER_AGENT is not set. "
            "SEC EDGAR requires a real contact: add to .env\n"
            "  EDGAR_USER_AGENT=finrag/0.1 your-email@example.com"
        )
    return val


# ----- Embedding -----

def _required_env_value(env_var: str, value: str) -> str:
    if not value:
        raise RuntimeError(f"{env_var} is not set.")
    return value


def embedding_model() -> str:
    return _required_env_value("EMBEDDING_MODEL", _get_settings().EMBEDDING_MODEL)


def embedding_dim() -> int:
    value = _get_settings().EMBEDDING_DIM
    if value is None:
        raise RuntimeError("EMBEDDING_DIM is not set.")
    return value


def nvidia_base_url() -> str:
    return _required_env_value("NVIDIA_BASE_URL", _get_settings().NVIDIA_BASE_URL)


def embedding_provider() -> str:
    return _get_settings().EMBEDDING_PROVIDER.lower()


# ----- Ingestion / retrieval (Wave 3) -----

def chunk_strategy() -> str:
    """Active chunking strategy: fixed | sentence_window | section | parent_doc."""
    return _get_settings().CHUNK_STRATEGY.lower()


def retrieval_mode() -> str:
    """Active retrieval strategy: dense | lexical | hybrid."""
    return _get_settings().RETRIEVAL_MODE.lower()


def query_rewrite_mode() -> str:
    """Active query-rewrite strategy: none | multi_query | hyde (Wave 3e)."""
    return _get_settings().QUERY_REWRITE.lower()


def rerank_enabled() -> bool:
    return _get_settings().RERANK_ENABLED


def rerank_candidates() -> int:
    return _get_settings().RERANK_CANDIDATES


def reranker_provider() -> str:
    return _get_settings().RERANKER_PROVIDER.lower()


def reranker_model() -> str:
    return _required_env_value("RERANKER_MODEL", _get_settings().RERANKER_MODEL)


def reranker_base_url() -> str:
    return _required_env_value("RERANKER_BASE_URL", _get_settings().RERANKER_BASE_URL)


# ----- API (Wave 5A) -----

def api_root_path() -> str:
    """Path prefix the app is mounted under behind a proxy (e.g. '/finrag'), or ''."""
    return _get_settings().API_ROOT_PATH


def api_token() -> str | None:
    """Bearer token required on mutating/expensive routes; None disables auth."""
    return _get_settings().API_TOKEN


def mcp_token() -> str | None:
    """Bearer token required by the MCP HTTP transport; None disables auth."""
    return _get_settings().MCP_TOKEN


def rate_limit_enabled() -> bool:
    """Whether the expensive API routes enforce per-token/IP rate limits."""
    return _get_settings().RATE_LIMIT_ENABLED


# ----- Guardrails (Wave 6) -----

def guardrails_enabled() -> bool:
    """Whether the ask/agent path runs the deterministic input/context/output screens."""
    return _get_settings().GUARDRAILS_ENABLED


def nemoguard_enabled() -> bool:
    """Whether input screening also consults the NVIDIA NemoGuard content-safety model."""
    return _get_settings().NEMOGUARD_ENABLED


def nemoguard_content_safety_model() -> str:
    return _required_env_value(
        "NEMOGUARD_CONTENT_SAFETY_MODEL", _get_settings().NEMOGUARD_CONTENT_SAFETY_MODEL
    )
