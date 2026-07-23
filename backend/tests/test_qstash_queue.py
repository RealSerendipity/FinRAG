"""QStash runtime configuration tests."""

from __future__ import annotations

import json

import pytest

from src import qstash_queue


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


def test_publish_ingest_item_sets_retry_dedupe_and_failure_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = {}

    class _Messages:
        def publish_json(self, **kwargs):
            published.update(kwargs)
            return type("_Result", (), {"message_id": "msg-123"})()

    class _Client:
        message = _Messages()

    monkeypatch.setattr(qstash_queue, "_client", lambda: _Client())
    monkeypatch.setattr(
        qstash_queue.config,
        "finrag_public_api_url",
        lambda: "https://api.example.com",
    )

    message_id = qstash_queue.publish_ingest_item("item-1")

    assert message_id == "msg-123"
    assert published == {
        "url": "https://api.example.com/internal/ingest/run",
        "body": {"item_id": "item-1"},
        "retries": 3,
        "failure_callback": "https://api.example.com/internal/ingest/failure",
        "deduplication_id": "item-1",
    }


def test_verify_uses_raw_body_signature_and_exact_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = {}

    class _Receiver:
        def verify(self, **kwargs):
            verified.update(kwargs)
            return object()

    monkeypatch.setattr(qstash_queue, "_receiver", lambda: _Receiver())
    body = json.dumps({"item_id": "item-1"}, separators=(",", ":")).encode()

    result = qstash_queue.verify(
        body=body,
        signature="signed",
        url="https://api.example.com/internal/ingest/run",
    )

    assert result is None
    assert verified == {
        "body": body.decode(),
        "signature": "signed",
        "url": "https://api.example.com/internal/ingest/run",
    }


def test_verify_propagates_receiver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_error = ValueError("invalid signature")

    class _Receiver:
        def verify(self, **kwargs):
            raise expected_error

    monkeypatch.setattr(qstash_queue, "_receiver", lambda: _Receiver())

    with pytest.raises(ValueError) as caught:
        qstash_queue.verify(
            body=b'{"item_id":"item-1"}',
            signature="invalid",
            url="https://api.example.com/internal/ingest/run",
        )

    assert caught.value is expected_error
