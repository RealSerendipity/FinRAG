"""Wave 1b smoke tests: dense retrieval + cited answer over local fixture."""

from __future__ import annotations

import os

import pytest

import src.config  # triggers load_dotenv()


def _skip_unless(*env_vars: str) -> None:
    for var in env_vars:
        if not os.environ.get(var):
            pytest.skip(f"{var} not set")


# ---------------------------------------------------------------------------
# retrieve.py
# ---------------------------------------------------------------------------

def test_retrieve_returns_results() -> None:
    _skip_unless("DATABASE_URL", "NVIDIA_API_KEY")
    from src.retrieve import retrieve
    results = retrieve("revenue", ticker="DEMO", period="FY2024", top_k=3)
    assert len(results) > 0
    assert all("id" in r and "content" in r for r in results)


def test_retrieve_filter_limits_results() -> None:
    _skip_unless("DATABASE_URL", "NVIDIA_API_KEY")
    from src.retrieve import retrieve
    results = retrieve("revenue", ticker="NONEXISTENT", top_k=5)
    assert results == []


def test_retrieve_distance_ascending() -> None:
    _skip_unless("DATABASE_URL", "NVIDIA_API_KEY")
    from src.retrieve import retrieve
    results = retrieve("net income profit margin", ticker="DEMO", top_k=3)
    distances = [r["distance"] for r in results]
    assert distances == sorted(distances), "Results must be ordered by ascending distance"


# ---------------------------------------------------------------------------
# rag.py
# ---------------------------------------------------------------------------

def test_ask_returns_cited_answer() -> None:
    _skip_unless("DATABASE_URL", "NVIDIA_API_KEY", "LLM_PROVIDER")
    from src.rag import ask
    answer = ask("What was DEMO Corp's revenue in FY2024?", ticker="DEMO", period="FY2024")
    assert answer.text
    assert len(answer.citations) > 0
    assert all(isinstance(c.chunk_id, int) for c in answer.citations)


def test_ask_rejects_hallucinated_citation() -> None:
    """Patch retrieve + chat — no real API calls needed for this safety check."""
    import unittest.mock as mock
    from src import rag

    fake_chunks = [{"id": 99999, "content": "Revenue was $12.5B", "section": None,
                    "chunk_index": 0, "metadata": {}, "distance": 0.1}]

    # Return a response that cites a non-existent chunk_id.
    fake_resp = mock.MagicMock()
    fake_resp.text = '{"text": "Revenue was high.", "citations": [{"chunk_id": 1, "quote": "Revenue was $12.5B"}]}'

    with mock.patch("src.rag.retrieve", return_value=fake_chunks), \
         mock.patch("src.rag.chat", return_value=fake_resp):
        with pytest.raises(ValueError, match="hallucination"):
            rag.ask("What was revenue?")
