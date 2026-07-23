"""Generic HTTP fetch with exponential back-off on 429 / 5xx."""
from __future__ import annotations

import threading
import time

import httpx

# Shared client — reuses TCP connections and TLS sessions across all requests
# in the same process (important for EDGAR ingest which hits the same hosts repeatedly).
_client = httpx.Client(timeout=60, follow_redirects=True)

# SEC EDGAR fair use caps clients at 10 req/s; batch ingest fires many requests
# back-to-back, so space them process-wide instead of only reacting to 429s.
_MIN_INTERVAL_S = 0.11
_throttle_lock = threading.Lock()
_next_allowed = 0.0


def _throttle() -> None:
    """Block until the next request slot; keeps spacing >= _MIN_INTERVAL_S.

    The lock hands out monotonically increasing slots, so concurrent threads
    queue up instead of bursting past the rate cap together.
    """
    global _next_allowed
    with _throttle_lock:
        now = time.monotonic()
        wait = _next_allowed - now
        _next_allowed = max(now, _next_allowed) + _MIN_INTERVAL_S
    if wait > 0:
        time.sleep(wait)


def fetch(url: str, *, headers: dict[str, str], retries: int = 3) -> bytes:
    """GET with exponential back-off on 429 / 5xx and transient transport errors.

    Raises httpx.HTTPStatusError (or httpx.TransportError) on final failure. SEC
    endpoints intermittently drop the TLS connection (SSL EOF / connect reset);
    retrying transport errors keeps ingest and the XBRL tool from failing on a
    single blip — the same resilience pattern used by db.py and the NVIDIA client.
    """
    delay = 1.0
    for attempt in range(retries):
        _throttle()
        try:
            resp = _client.get(url, headers=headers)
        except httpx.TransportError:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
        resp.raise_for_status()
        return resp.content
    resp.raise_for_status()
    return resp.content  # unreachable; satisfies type checker
