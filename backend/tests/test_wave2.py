"""Wave 2 tests: eval metrics math + questions.jsonl schema. All offline."""

from __future__ import annotations

import json
from pathlib import Path

from eval import metrics

QUESTIONS_PATH = Path(__file__).parent.parent / "eval" / "questions.jsonl"
CATEGORIES = {"numeric", "table", "cross-document", "reasoning", "consistency"}


# ---------------------------------------------------------------------------
# Relevance matching
# ---------------------------------------------------------------------------

def test_matches_or_of_and() -> None:
    groups = [["iphone", "201,183"], ["391,035"]]
    assert metrics.matches("iPhone $ 201,183 net sales", groups)
    assert metrics.matches("Total net sales $ 391,035", groups)
    assert not metrics.matches("iPhone sales were flat", groups)  # AND not satisfied
    assert not metrics.matches("anything", [])


def test_matches_normalizes_whitespace() -> None:
    # Filings contain non-breaking spaces: "$132.4\xa0billion".
    assert metrics.matches("totaled $132.4\xa0billion as of", [["132.4 billion"]])


def test_relevant_ranks() -> None:
    contents = ["nothing", "has 391,035 here", "nothing", "391,035 again"]
    assert metrics.relevant_ranks(contents, [["391,035"]]) == [2, 4]


# ---------------------------------------------------------------------------
# Retrieval metric math
# ---------------------------------------------------------------------------

def test_hit_and_recall_at_k() -> None:
    assert metrics.hit_at_k([3, 7], 5) is True
    assert metrics.hit_at_k([7], 5) is False
    assert metrics.recall_at_k([1, 4, 20], 5, 3) == 2 / 3
    assert metrics.recall_at_k([], 5, 0) is None


def test_mrr() -> None:
    assert metrics.mrr([3, 5]) == 1 / 3
    assert metrics.mrr([]) == 0.0


def test_ndcg_perfect_ranking_is_one() -> None:
    assert metrics.ndcg_at_k([1, 2, 3], 5, 3) == 1.0


def test_ndcg_worse_ranking_below_one() -> None:
    val = metrics.ndcg_at_k([2, 4], 5, 2)
    assert val is not None and 0.0 < val < 1.0
    assert metrics.ndcg_at_k([], 5, 0) is None


def test_doc_coverage_at_k() -> None:
    ranked = ["acc-a", "acc-a", "acc-b", "acc-c"]
    assert metrics.doc_coverage_at_k(ranked, ["acc-a", "acc-b"], 3) == 1.0
    assert metrics.doc_coverage_at_k(ranked, ["acc-a", "acc-c"], 3) == 0.5
    assert metrics.doc_coverage_at_k(ranked, [], 3) is None


def test_mean_skips_none() -> None:
    assert metrics.mean([1.0, None, 0.0]) == 0.5
    assert metrics.mean([None]) is None


# ---------------------------------------------------------------------------
# Judge output parsing
# ---------------------------------------------------------------------------

def test_parse_json_obj_plain_and_fenced() -> None:
    plain = '{"faithful": true, "reason": "ok"}'
    fenced = 'sure!\n```json\n{"faithful": false, "reason": "bad"}\n```'
    assert metrics.parse_json_obj(plain, "faithful")["faithful"] is True
    assert metrics.parse_json_obj(fenced, "faithful")["faithful"] is False
    assert metrics.parse_json_obj("no json here", "faithful") is None


# ---------------------------------------------------------------------------
# questions.jsonl schema
# ---------------------------------------------------------------------------

def _load_items() -> list[dict]:
    lines = [ln for ln in QUESTIONS_PATH.read_text().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_questions_size_and_unique_ids() -> None:
    items = _load_items()
    assert 30 <= len(items) <= 50
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids))


def test_questions_cover_all_categories() -> None:
    items = _load_items()
    by_cat: dict[str, int] = {}
    for it in items:
        assert it["category"] in CATEGORIES
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    assert set(by_cat) == CATEGORIES
    assert all(n >= 5 for n in by_cat.values())


def test_questions_required_fields() -> None:
    for it in _load_items():
        assert it["question"].strip()
        assert it["ticker"] == "AAPL" or it["ticker"]
        assert isinstance(it["expected_accessions"], list)
        assert isinstance(it["relevance"], list)
        assert it["expected_answer"].strip()
        if it["relevance"]:  # positive item
            assert it["expected_accessions"], f"{it['id']}: positive item needs accessions"
            assert all(
                grp and all(t.strip() for t in grp) for grp in it["relevance"]
            ), f"{it['id']}: empty relevance term"
        else:  # insufficient-context item
            assert it["expected_answer"] == "Insufficient context"


def test_questions_paired_with_references_exist() -> None:
    items = _load_items()
    ids = {it["id"] for it in items}
    for it in items:
        ref = it.get("paired_with")
        if ref is not None:
            assert ref in ids, f"{it['id']}: paired_with {ref!r} not found"
            assert it["category"] == "consistency"
