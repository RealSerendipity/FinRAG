"""Wave 3 tests: chunking strategies, query rewriting, retrieval/rerank dispatch,
table serialization. All offline — no DB, no API keys required."""

from __future__ import annotations

import pytest

from src.financial.table_extract import _serialize
from src.ingest import (
    VALID_CHUNK_STRATEGIES,
    build_chunks,
    chunk_parent_doc,
    chunk_sentence_window,
    validate_chunk_strategy,
)
from src.query_rewrite import normalize_query
from src.rag import _context_text, _extract_answer_obj
from src.rerank import rerank
from src.retrieve import retrieve

# ---------------------------------------------------------------------------
# Chunking strategies (Wave 3a)
# ---------------------------------------------------------------------------
_TEXT = (
    "Apple reported record revenue. Revenue grew two percent. R&D spending rose.\n\n"
    "Gross margin improved. Services hit an all-time high. Cash flow was strong. "
    "Buybacks continued through the year. Dividends were paid each quarter."
)


def test_sentence_window_overlaps_and_bounds() -> None:
    chunks = chunk_sentence_window(_TEXT, window=3, stride=2)
    assert len(chunks) >= 2
    # stride < window ⇒ consecutive windows share a sentence (overlap).
    assert any("Revenue grew two percent." in c for c in chunks)


def test_sentence_window_rejects_bad_params() -> None:
    with pytest.raises(ValueError):
        chunk_sentence_window(_TEXT, window=0)


def test_parent_doc_pairs_share_parent() -> None:
    pairs = chunk_parent_doc(_TEXT, child_tokens=20, parent_tokens=200)
    assert pairs and all(len(p) == 2 for p in pairs)
    # Every child is contained in its parent text.
    assert all(child in parent for child, parent in pairs)


def test_build_chunks_dispatch_and_metadata() -> None:
    assert all(meta == {} for _, meta in build_chunks(_TEXT, "fixed"))
    assert all(meta == {} for _, meta in build_chunks(_TEXT, "sentence_window"))
    assert all(meta == {} for _, meta in build_chunks(_TEXT, "section"))
    pd = build_chunks(_TEXT, "parent_doc")
    assert all("parent_text" in meta for _, meta in pd)
    with pytest.raises(ValueError):
        build_chunks(_TEXT, "bogus")


# ---------------------------------------------------------------------------
# Configurable chunk strategy (validation + parent_doc context wiring)
# ---------------------------------------------------------------------------
def test_validate_chunk_strategy() -> None:
    assert set(VALID_CHUNK_STRATEGIES) == {"fixed", "sentence_window", "section", "parent_doc"}
    assert validate_chunk_strategy("FIXED") == "fixed"  # normalizes case
    with pytest.raises(ValueError, match="Unknown chunk strategy"):
        validate_chunk_strategy("bogus")


def test_context_text_prefers_parent() -> None:
    # parent_doc: LLM context should be the parent block, not the small child.
    assert _context_text({"content": "child", "metadata": {"parent_text": "PARENT"}}) == "PARENT"
    # other strategies: no parent_text → fall back to the chunk content.
    assert _context_text({"content": "child", "metadata": {}}) == "child"
    assert _context_text({"content": "child", "metadata": None}) == "child"


def test_cli_chunk_strategy_flag_validates() -> None:
    from click.testing import CliRunner

    from src.cli import cli

    runner = CliRunner()
    # Bad value is rejected by click.Choice before any network/DB work.
    bad = runner.invoke(cli, ["ingest", "--tickers", "AAPL", "--year", "2024",
                              "--chunk-strategy", "bogus"])
    assert bad.exit_code != 0
    assert "bogus" in bad.output or "Invalid value" in bad.output


# ---------------------------------------------------------------------------
# Query rewriting (Wave 3e)
# ---------------------------------------------------------------------------
def test_normalize_query_expands_abbreviations() -> None:
    expanded = "research and development and capital expenditures"
    assert normalize_query("  R&D   and CapEx ") == expanded
    assert normalize_query("EPS YoY") == "earnings per share year over year"


# ---------------------------------------------------------------------------
# Retrieval + rerank dispatch (Wave 3c/3d)
# ---------------------------------------------------------------------------
def test_retrieve_rejects_unknown_mode() -> None:
    # Mode is validated before any embedding/DB work.
    with pytest.raises(ValueError, match="Unknown retrieval mode"):
        retrieve("revenue", ticker="AAPL", top_k=5, mode="banana")


def test_retrieve_rejects_unknown_rewrite() -> None:
    # Query-rewrite mode is validated before any embedding/DB work (Wave 3e).
    with pytest.raises(ValueError, match="Unknown query rewrite"):
        retrieve("revenue", ticker="AAPL", top_k=5, rewrite="banana")


def test_rerank_empty_is_noop() -> None:
    assert rerank("q", [], top_k=5) == []


# ---------------------------------------------------------------------------
# Robust Answer-JSON extraction (handles reasoning models that leak CoT + multi-JSON)
# ---------------------------------------------------------------------------
def test_extract_answer_obj_picks_last_answer() -> None:
    raw = (
        '{"text": "112,010", "citations": [{"chunk_id": 1, "quote": "a"}]}\n'
        "reasoning prose that would break a greedy first-to-last span...\n"
        '{"text": "93,736", "citations": [{"chunk_id": 2, "quote": "Net income 93,736"}]}'
    )
    obj = _extract_answer_obj(raw)
    assert obj is not None and obj["text"] == "93,736"


def test_extract_answer_obj_clean_fenced_and_garbage() -> None:
    assert _extract_answer_obj('{"text": "x", "citations": []}')["text"] == "x"
    assert _extract_answer_obj('```json\n{"text": "y", "citations": []}\n```')["text"] == "y"
    assert _extract_answer_obj('{"text": "a {b} c", "citations": []}')["text"] == "a {b} c"
    assert _extract_answer_obj("no json here") is None


# ---------------------------------------------------------------------------
# Table serialization (Wave 3b) — pure function, no Docling needed
# ---------------------------------------------------------------------------
def test_serialize_compacts_and_drops_empty() -> None:
    md = (
        "|   |   |   |\n"
        "|---|---|---|\n"
        "| iPhone | iPhone | $ | 201,183 |   |   |\n"
        "|   |   |   |\n"
        "| Mac |   | $ | 29,984 |\n"
    )
    out = _serialize(md)
    lines = out.splitlines()
    # Empty/separator rows dropped; consecutive duplicate cells collapsed.
    assert "iPhone | $ | 201,183" in lines[0]
    assert "Mac | $ | 29,984" in lines[1]
    assert all(set(ln) != {"|", "-", " "} for ln in lines)
