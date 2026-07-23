"""QStash runtime configuration tests."""

from __future__ import annotations

import pytest


def test_qstash_configuration_accessors_normalize_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src import config

    monkeypatch.setenv("FINRAG_PUBLIC_API_URL", " https://api.example.test/ ")
    monkeypatch.setenv("QSTASH_TOKEN", " token ")
    monkeypatch.setenv("QSTASH_CURRENT_SIGNING_KEY", " current ")
    monkeypatch.setenv("QSTASH_NEXT_SIGNING_KEY", " next ")

    assert config.finrag_public_api_url() == "https://api.example.test"
    assert config.qstash_token() == "token"
    assert config.qstash_signing_keys() == ("current", "next")


@pytest.mark.parametrize(
    ("env_var", "helper_name"),
    [
        ("FINRAG_PUBLIC_API_URL", "finrag_public_api_url"),
        ("QSTASH_TOKEN", "qstash_token"),
        ("QSTASH_CURRENT_SIGNING_KEY", "qstash_signing_keys"),
        ("QSTASH_NEXT_SIGNING_KEY", "qstash_signing_keys"),
    ],
)
def test_qstash_configuration_accessors_require_each_value(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    helper_name: str,
) -> None:
    from src import config

    monkeypatch.setenv("FINRAG_PUBLIC_API_URL", "https://api.example.test")
    monkeypatch.setenv("QSTASH_TOKEN", "token")
    monkeypatch.setenv("QSTASH_CURRENT_SIGNING_KEY", "current")
    monkeypatch.setenv("QSTASH_NEXT_SIGNING_KEY", "next")
    monkeypatch.delenv(env_var, raising=False)

    helper = getattr(config, helper_name)
    with pytest.raises(RuntimeError, match=f"{env_var} is not set"):
        helper()
