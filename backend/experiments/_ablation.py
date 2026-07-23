"""Shared harness for Wave 3 retrieval ablations.

Retrieval metrics (recall@k / MRR / nDCG@k / hit@k) depend only on what a
retriever returns, not on any LLM, so an A/B over retrieval variants needs no
judge. The DB (Neon free tier) makes per-query round-trips slow and shipping the
1024-d embeddings out is pathologically slow, so the whole sweep is reduced to a
few batched round-trips:

- content load  — one query pulls chunk id/ticker/year/content (NO embeddings);
- dense         — ONE batched LATERAL query runs all per-item vector searches
  server-side (pgvector `<=>`), returning only ranked chunk ids;
- lexical       — ONE batched query returns Postgres FTS rankings (faithful
  ts_rank_cd, same OR-tsquery rewrite as src/retrieve.py);
- hybrid        — RRF fusion of the dense and lexical id-rankings, in Python.

Everything is faithful to the production src/retrieve.py ordering.

Recall uses a TRUE denominator — the count of keyword-relevant chunks in the
filtered corpus — so recall is comparable across variants. Relevance is the same
OR-of-AND keyword convention as eval/questions.jsonl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from eval import metrics  # noqa: E402
from src import db  # noqa: E402
from src.embed import embed  # noqa: E402
from src.retrieve import RRF_K  # noqa: E402

QUESTIONS_PATH = _ROOT / "eval" / "questions.jsonl"
KS = (5, 10)


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_items(
    *, positive_only: bool = True, categories: tuple[str, ...] | None = None
) -> list[dict]:
    items = [json.loads(ln) for ln in QUESTIONS_PATH.read_text().splitlines() if ln.strip()]
    if positive_only:
        items = [it for it in items if it["relevance"]]
    if categories:
        items = [it for it in items if it["category"] in categories]
    return items


def load_content(tickers: list[str]) -> dict[int, dict]:
    """Load chunk metadata + content (no embeddings): id -> {id, ticker, year, content}."""
    sql = """
        SELECT c.id, co.ticker, EXTRACT(YEAR FROM d.period)::int AS yr, c.content
        FROM chunks c
        JOIN documents d  ON c.document_id = d.id
        JOIN companies co ON d.company_id  = co.id
        WHERE co.ticker = ANY(%s)
    """
    with db.get_conn() as conn:
        rows = conn.execute(sql, [list(tickers)]).fetchall()
    return {cid: {"id": cid, "ticker": tk, "year": yr, "content": content}
            for cid, tk, yr, content in rows}


def _year(period: str | None) -> int | None:
    if not period:
        return None
    if period.startswith("FY"):
        return int(period[2:])
    if len(period) == 4 and period.isdigit():
        return int(period)
    return None


def _vlit(vec) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


# --------------------------------------------------------------------------- #
# Batched rankers (server-side; return id-rankings)
# --------------------------------------------------------------------------- #
def dense_rank_all(
    items: list[dict], k: int, *, ignore_period: bool = False
) -> dict[str, list[int]]:
    """One batched LATERAL pgvector search per item; item_id -> ranked chunk ids."""
    vecs = embed([it["question"] for it in items], input_type="query")
    values, params = [], []
    for it, v in zip(items, vecs, strict=True):
        yr = None if ignore_period else _year(it.get("period"))
        values.append("(%s::text, %s::vector, %s::text, %s::int)")
        params += [it["id"], _vlit(v), it["ticker"], yr]
    sql = f"""
        WITH q(iid, qv, tk, yr) AS (VALUES {", ".join(values)})
        SELECT q.iid, t.id, t.rnk
        FROM q CROSS JOIN LATERAL (
            SELECT c.id, ROW_NUMBER() OVER (ORDER BY c.embedding <=> q.qv) AS rnk
            FROM chunks c
            JOIN documents d  ON c.document_id = d.id
            JOIN companies co ON d.company_id  = co.id
            WHERE co.ticker = q.tk
              AND (q.yr IS NULL OR EXTRACT(YEAR FROM d.period)::int = q.yr)
            ORDER BY c.embedding <=> q.qv
            LIMIT %s
        ) t
        ORDER BY q.iid, t.rnk
    """
    params.append(k)
    return _collect(sql, params, items)


def fts_rank_all(items: list[dict], k: int, *, ignore_period: bool = False) -> dict[str, list[int]]:
    """One batched Postgres FTS query; item_id -> ranked chunk ids.

    Uses the same OR-tsquery rewrite as src/retrieve.py (plainto ANDs, too strict
    for QA-style queries) so ordering is faithful to the production lexical path.
    """
    values, params = [], []
    for it in items:
        yr = None if ignore_period else _year(it.get("period"))
        values.append("(%s::text, %s::text, %s::text, %s::int)")
        params += [it["id"], it["question"], it["ticker"], yr]
    sql = f"""
        WITH q(iid, qt, tk, yr) AS (VALUES {", ".join(values)}),
        scored AS (
            SELECT q.iid, c.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY q.iid
                       ORDER BY ts_rank_cd(
                           c.tsv,
                           replace(plainto_tsquery('english', q.qt)::text, '&', '|')::tsquery
                       ) DESC
                   ) AS rnk
            FROM q
            JOIN companies co ON co.ticker = q.tk
            JOIN documents d  ON d.company_id = co.id
            JOIN chunks c     ON c.document_id = d.id
                             AND c.tsv @@ replace(
                                 plainto_tsquery('english', q.qt)::text, '&', '|'
                             )::tsquery
            WHERE (q.yr IS NULL OR EXTRACT(YEAR FROM d.period)::int = q.yr)
        )
        SELECT iid, id, rnk FROM scored WHERE rnk <= %s ORDER BY iid, rnk
    """
    params.append(k)
    return _collect(sql, params, items)


def dense_rank_ablation(items: list[dict], strategy: str, k: int) -> dict[str, list[int]]:
    """Batched LATERAL pgvector search against the chunks_ablation table for a strategy."""
    vecs = embed([it["question"] for it in items], input_type="query")
    values, params = [], []
    for it, v in zip(items, vecs, strict=True):
        values.append("(%s::text, %s::vector, %s::text, %s::int)")
        params += [it["id"], _vlit(v), it["ticker"], _year(it.get("period"))]
    sql = f"""
        WITH q(iid, qv, tk, yr) AS (VALUES {", ".join(values)})
        SELECT q.iid, t.id, t.rnk FROM q CROSS JOIN LATERAL (
            SELECT c.id, ROW_NUMBER() OVER (ORDER BY c.embedding <=> q.qv) AS rnk
            FROM chunks_ablation c
            WHERE c.strategy = %s AND c.ticker = q.tk
              AND (q.yr IS NULL OR c.year = q.yr)
            ORDER BY c.embedding <=> q.qv LIMIT %s
        ) t ORDER BY q.iid, t.rnk
    """
    params += [strategy, k]
    return _collect(sql, params, items)


def content_for_ablation(strategy: str) -> dict[int, dict]:
    """Load id -> {id, ticker, year, content} for one chunks_ablation strategy."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, year, content FROM chunks_ablation WHERE strategy = %s",
            [strategy],
        ).fetchall()
    return {r[0]: {"id": r[0], "ticker": r[1], "year": r[2], "content": r[3]} for r in rows}


def _collect(sql: str, params: list, items: list[dict]) -> dict[str, list[int]]:
    with db.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: dict[str, list[int]] = {it["id"]: [] for it in items}
    for row in rows:
        out[row[0]].append(row[1])
    return out


def rrf_ids(id_lists: list[list[int]], k: int = RRF_K, pool: int | None = None) -> list[int]:
    """RRF-fuse several ranked id lists into one ranked id list."""
    scores: dict[int, float] = {}
    for ids in id_lists:
        for rank, cid in enumerate(ids[:pool] if pool else ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda i: scores[i], reverse=True)


def chunks_from_ids(ids: list[int], content: dict[int, dict], k: int | None = None) -> list[dict]:
    out = [content[i] for i in ids if i in content]
    return out[:k] if k else out


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def totals_from_content(items: list[dict], content: dict[int, dict], *,
                        ignore_period: bool = False) -> dict[str, int]:
    """True recall denominator per item, computed from the in-memory content map."""
    totals: dict[str, int] = {}
    for it in items:
        yr = None if ignore_period else _year(it.get("period"))
        totals[it["id"]] = sum(
            1
            for c in content.values()
            if c["ticker"] == it["ticker"]
            and (yr is None or c["year"] == yr)
            and metrics.matches(c["content"], it["relevance"])
        )
    return totals


def eval_variant(retrieve_fn, items: list[dict], totals: dict[str, int]) -> dict:
    """Run one retrieval variant over all items; return aggregate + per-item rows.

    retrieve_fn(item) must return a ranked list of chunk dicts (with `content`).
    """
    rows = []
    for it in items:
        chunks = retrieve_fn(it)
        contents = [c["content"] for c in chunks]
        ranks = metrics.relevant_ranks(contents, it["relevance"])
        total = totals[it["id"]]
        row = {"id": it["id"], "category": it["category"], "ranks": ranks,
               "total_rel": total, "mrr": metrics.mrr(ranks)}
        for k in KS:
            row[f"hit@{k}"] = metrics.hit_at_k(ranks, k)
            row[f"recall@{k}"] = metrics.recall_at_k(ranks, k, total)
            row[f"ndcg@{k}"] = metrics.ndcg_at_k(ranks, k, total)
        rows.append(row)
    return {"agg": _aggregate(rows), "rows": rows}


def _aggregate(rows: list[dict]) -> dict:
    agg: dict = {"n": len(rows), "mrr": metrics.mean([r["mrr"] for r in rows])}
    for k in KS:
        agg[f"hit@{k}"] = metrics.mean([1.0 if r[f"hit@{k}"] else 0.0 for r in rows])
        agg[f"recall@{k}"] = metrics.mean([r[f"recall@{k}"] for r in rows])
        agg[f"ndcg@{k}"] = metrics.mean([r[f"ndcg@{k}"] for r in rows])
    return agg


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def fmt(v, digits: int = 3) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def comparison_table(variants: list[tuple[str, dict]]) -> list[str]:
    metric_keys = ["recall@5", "recall@10", "mrr", "ndcg@10", "hit@5", "hit@10"]
    header = "| variant | " + " | ".join(metric_keys) + " |"
    sep = "|" + "---|" * (len(metric_keys) + 1)
    lines = [header, sep]
    for name, agg in variants:
        cells = " | ".join(fmt(agg[m]) for m in metric_keys)
        lines.append(f"| {name} | {cells} |")
    return lines


def delta_line(base: dict, new: dict, key: str = "recall@10") -> str:
    b, n = base[key], new[key]
    if b is None or n is None:
        return f"{key}: — → —"
    return f"{key} {b:.3f} → {n:.3f} (Δ {n - b:+.3f})"


def write_report(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")
