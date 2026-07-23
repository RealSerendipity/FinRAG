"""QStash publishing and signature verification for ingestion jobs."""

from __future__ import annotations

from qstash import QStash, Receiver

from src import config

_RETRIES = 3


def _client() -> QStash:
    return QStash(config.qstash_token())


def _receiver() -> Receiver:
    current, next_key = config.qstash_signing_keys()
    return Receiver(
        current_signing_key=current,
        next_signing_key=next_key,
    )


def publish_ingest_item(item_id: str) -> str:
    """Publish one ingestion item and return its QStash message ID."""
    base_url = config.finrag_public_api_url()
    result = _client().message.publish_json(
        url=f"{base_url}/internal/ingest/run",
        body={"item_id": item_id},
        retries=_RETRIES,
        failure_callback=f"{base_url}/internal/ingest/failure",
        deduplication_id=item_id,
    )
    return result.message_id


def verify(*, body: bytes, signature: str, url: str) -> None:
    """Verify a QStash signature against the raw body and exact request URL."""
    _receiver().verify(
        body=body.decode("utf-8"),
        signature=signature,
        url=url,
    )
