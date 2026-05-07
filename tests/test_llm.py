"""Wave 0 smoke tests for the LLM dispatch.

Each provider test runs only when its API key is set; otherwise it is skipped.
The Gemini test is the project's primary path and should pass in any properly
configured environment.
"""

from __future__ import annotations

import os

import pytest

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
        if any(k in msg for k in ("quota", "rate_limit", "insufficient_quota", "429")):
            pytest.skip(f"{provider} quota/rate-limit: {exc}")
        raise
    _assert_hello(resp)
    assert resp.provider == provider


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        chat(messages=[{"role": "user", "content": "x"}], provider="banana")
