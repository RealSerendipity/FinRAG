"""Wave 1c tests: chunk_text unit tests + live ingest smoke test."""

from __future__ import annotations

import os

import pytest
import tiktoken

from src.ingest import chunk_text

_ENCODING = tiktoken.get_encoding("cl100k_base")
_MAX = 100  # small limit keeps unit tests fast; production default is 300


def test_chunk_text_size():
    """Every chunk must be at most max_tokens tokens."""
    long_text = "\n\n".join(["word " * 80 for _ in range(30)])
    chunks = chunk_text(long_text, max_tokens=_MAX)
    assert chunks, "Expected at least one chunk"
    for chunk in chunks:
        assert len(_ENCODING.encode(chunk)) <= _MAX


def test_chunk_text_nonempty():
    """Chunks must be non-empty strings."""
    text = "Hello world.\n\nThis is a test paragraph.\n\nAnother paragraph here."
    chunks = chunk_text(text, max_tokens=_MAX)
    assert len(chunks) >= 1
    assert all(c.strip() for c in chunks)


def test_chunk_text_oversized_paragraph():
    """Single oversized paragraph must be split into multiple chunks."""
    para = "word " * 300  # ~300 tokens, way over max_tokens=100
    chunks = chunk_text(para, max_tokens=_MAX)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(_ENCODING.encode(chunk)) <= _MAX


def test_chunk_text_empty():
    """Empty input returns empty list."""
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_invalid_max_tokens():
    """max_tokens <= 0 must raise ValueError."""
    with pytest.raises(ValueError, match="max_tokens"):
        chunk_text("some text", max_tokens=0)
    with pytest.raises(ValueError, match="max_tokens"):
        chunk_text("some text", max_tokens=-1)


def test_chunk_text_paragraph_boundaries():
    """Paragraph-split text should produce multiple chunks respecting \\n\\n."""
    short_paras = "\n\n".join([f"Para {i}." for i in range(10)])
    chunks = chunk_text(short_paras, max_tokens=_MAX)
    # All chunks combined should cover all paragraph text.
    combined = " ".join(chunks)
    for i in range(10):
        assert f"Para {i}." in combined


@pytest.mark.skipif(
    not os.getenv("NVIDIA_API_KEY") or not os.getenv("DATABASE_URL"),
    reason="NVIDIA_API_KEY and DATABASE_URL required for live ingest",
)
def test_ingest_live_aapl():
    import httpx

    from src.ingest import ingest

    try:
        n = ingest("AAPL", fiscal_year=2024)
    except httpx.ConnectError as exc:
        pytest.skip(f"EDGAR unreachable (network/VPN): {exc}")
    assert n > 0, "Expected at least one chunk after ingesting AAPL 2024 10-K"
