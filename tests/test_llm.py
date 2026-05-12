"""Wave 0 smoke tests for the LLM dispatch.

Each provider test runs only when its API key is set; otherwise it is skipped.
The Gemini test is the project's primary path and should pass in any properly
configured environment.
"""

from __future__ import annotations

import os

import pytest

from src import config
from src.llm import LLMResponse, chat


def _skip_unless_key(env_var: str) -> None:
    if not os.environ.get(env_var):
        pytest.skip(f"{env_var} not set")


def _assert_hello(resp: LLMResponse) -> None:
    assert isinstance(resp, LLMResponse)
    assert resp.text, "empty response text"
    assert "hello" in resp.text.lower()
    assert resp.usage.get("input_tokens", 0) > 0
    assert resp.usage.get("output_tokens", 0) > 0


@pytest.mark.parametrize(
    ("provider", "env_var"),
    [
        ("gemini", "GEMINI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("nvidia", "NVIDIA_API_KEY"),
    ],
)
def test_chat_hello_world(provider: str, env_var: str) -> None:
    _skip_unless_key(env_var)
    try:
        resp = chat(
            messages=[{"role": "user", "content": "Reply with exactly the word: hello"}],
            provider=provider,
            temperature=0.0,
            max_tokens=16,
        )
    except Exception as exc:
        # Skip on quota / billing errors so CI isn't polluted by account state.
        msg = str(exc).lower()
        if any(
            k in msg
            for k in ("quota", "rate_limit", "insufficient_quota", "credit", "billing", "429")
        ):
            pytest.skip(f"{provider} quota/rate-limit: {exc}")
        raise
    _assert_hello(resp)
    assert resp.provider == provider


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        chat(messages=[{"role": "user", "content": "x"}], provider="banana")


def test_cross_provider_model_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model from a different provider must be rejected before any API call."""
    anthropic_models = "claude-haiku-4-5-20251001,claude-sonnet-4-6,claude-opus-4-7"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("ANTHROPIC_MODELS", anthropic_models)
    with pytest.raises(ValueError, match="not valid for provider"):
        config.llm_model()


def test_unknown_model_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Completely unknown model name must be rejected."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-99-turbo")
    monkeypatch.setenv("OPENAI_MODELS", "gpt-4.1-nano,gpt-4.1-mini,gpt-4.1,o3")
    with pytest.raises(ValueError, match="not valid for provider"):
        config.llm_model()


def test_judge_cross_provider_model_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Judge model from a different provider than judge_provider must be rejected."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_JUDGE_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.5-pro")
    with pytest.raises(ValueError, match="not valid for provider"):
        config.judge_model()


def test_judge_model_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid cross-provider judge config resolves without error."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    anthropic_models = "claude-haiku-4-5-20251001,claude-sonnet-4-6,claude-opus-4-7"
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_JUDGE_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("ANTHROPIC_MODELS", anthropic_models)
    assert config.judge_provider() == "anthropic"
    assert config.judge_model() == "claude-opus-4-7"


@pytest.mark.parametrize(
    ("provider", "model_env", "models", "expected_model"),
    [
        ("gemini", "GEMINI_MODELS", "gemini-first,gemini-second", "gemini-first"),
        (
            "anthropic",
            "ANTHROPIC_MODELS",
            "claude-first,claude-second",
            "claude-first",
        ),
        ("openai", "OPENAI_MODELS", "gpt-first,gpt-second", "gpt-first"),
        ("nvidia", "NVIDIA_MODELS", "nvidia-first,nvidia-second", "nvidia-first"),
    ],
)
def test_llm_model_resolves_provider_default_from_first_env_model(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model_env: str,
    models: str,
    expected_model: str,
) -> None:
    """llm_model() must use the first configured provider model when LLM_MODEL is unset."""
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv(model_env, models)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert config.llm_model() == expected_model


def test_judge_model_resolves_default_from_first_judge_provider_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """judge_model() must use the first configured judge-provider model by default."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODELS", "claude-first,claude-second")
    monkeypatch.delenv("LLM_JUDGE_MODEL", raising=False)

    assert config.judge_model() == "claude-first"


def test_llm_model_default_requires_provider_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default model resolution must fail when the provider model list is missing."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODELS", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_MODELS is not set"):
        config.llm_model()
