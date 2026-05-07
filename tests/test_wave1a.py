"""Wave 1a smoke tests: schema bootstrap + NVIDIA embedding."""

from __future__ import annotations

import os

import pytest

import src.config  # triggers load_dotenv() before any skip check


def _skip_unless(env_var: str) -> None:
    if not os.environ.get(env_var):
        pytest.skip(f"{env_var} not set")


def test_bootstrap_idempotent() -> None:
    _skip_unless("DATABASE_URL")
    from src.db import bootstrap
    bootstrap()
    bootstrap()  # second run must not raise


def test_embed_returns_1024d_vector() -> None:
    _skip_unless("NVIDIA_API_KEY")
    from src.embed import embed
    vecs = embed(["hello world"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 1024


def test_embed_multiple_texts() -> None:
    _skip_unless("NVIDIA_API_KEY")
    from src.embed import embed
    vecs = embed(["first sentence", "second sentence"])
    assert len(vecs) == 2
    assert all(len(v) == 1024 for v in vecs)


def test_embed_empty_returns_empty() -> None:
    from src.embed import embed
    assert embed([]) == []
