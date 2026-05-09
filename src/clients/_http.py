"""Generic HTTP fetch with exponential back-off on 429 / 5xx."""
from __future__ import annotations

import time

import httpx


def fetch(url: str, *, headers: dict[str, str], retries: int = 3) -> bytes:
    """GET with exponential back-off on 429 / 5xx. Raises httpx.HTTPStatusError on final failure."""
    delay = 1.0
    for attempt in range(retries):
        resp = httpx.get(url, headers=headers, timeout=60, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
        resp.raise_for_status()
        return resp.content
    resp.raise_for_status()
    return resp.content  # unreachable; satisfies type checker
