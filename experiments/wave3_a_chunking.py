"""Wave 3a — chunking strategy ablation: fixed vs sentence-window vs parent-doc.

Hypothesis: moving off fixed token/paragraph chunks to sentence-window (and
hierarchical parent-doc) chunks lifts recall@10, because narrative answers stop
being split across chunk boundaries. If fixed already wins, the corpus is
table/number heavy enough that narrative coherence does not matter.

Each strategy is re-chunked from the same cached filing text, embedded with the
same NVIDIA model, and written to a dedicated `chunks_ablation` table (the
production `chunks` table is left untouched). Dense recall is then measured per
strategy with one batched LATERAL pgvector query each.

Usage: uv run python experiments/wave3_a_chunking.py
"""

from __future__ import annotations

from pathlib import Path

import _ablation as ab

from src import db
from src.embed import embed
from src.financial.edgar import fetch_filing
from src.ingest import build_chunks

REPORT = Path(__file__).parent.parent / "eval" / "reports" / "wave_3a.md"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
STRATEGIES = ("fixed", "sentence_window", "parent_doc")
TOP_K = 10
EMBED_BATCH = 32


def filing_text(ticker: str, year: int) -> str:
    """Fetch a 10-K's stripped text, caching to data/raw to avoid repeated EDGAR hits."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{ticker}_{year}_10-K.txt"
    if cache.exists():
        return cache.read_text()
    filing = fetch_filing(ticker, "10-K", f"FY{year}")
    text = filing["text"] if isinstance(filing, dict) else filing.text
    cache.write_text(text)
    return text


def _embed_all(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        out.extend(embed(texts[i : i + EMBED_BATCH], input_type="passage"))
    return out


def _already_built() -> bool:
    """True if chunks_ablation already holds rows for every strategy (reuse it)."""
    with db.get_conn() as conn:
        exists = conn.execute("SELECT to_regclass('public.chunks_ablation')").fetchone()[0]
        if not exists:
            return False
        present = {
            r[0] for r in conn.execute("SELECT DISTINCT strategy FROM chunks_ablation").fetchall()
        }
    return set(STRATEGIES).issubset(present)


def setup_table(filings: list[tuple[str, int]]) -> None:
    if _already_built():
        print("  chunks_ablation already populated for all strategies; reusing.", flush=True)
        return
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS chunks_ablation")
        conn.execute(
            """
            CREATE TABLE chunks_ablation (
                id BIGSERIAL PRIMARY KEY,
                strategy TEXT, ticker TEXT, year INT,
                content TEXT, embedding VECTOR(1024)
            )
            """
        )
    for strategy in STRATEGIES:
        for ticker, year in filings:
            text = filing_text(ticker, year)
            records = build_chunks(text, strategy)
            contents = [c for c, _ in records]
            print(f"  {strategy} {ticker} {year}: {len(contents)} chunks, embedding...", flush=True)
            vectors = _embed_all(contents)
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO chunks_ablation (strategy, ticker, year, content, embedding) "
                        "VALUES (%s, %s, %s, %s, %s::vector)",
                        [(strategy, ticker, year, c, v)
                         for c, v in zip(contents, vectors, strict=True)],
                    )


def dense_rank_strategy(items: list[dict], strategy: str, k: int) -> dict[str, list[int]]:
    vecs = embed([it["question"] for it in items], input_type="query")
    values, params = [], []
    for it, v in zip(items, vecs, strict=True):
        yr = ab._year(it.get("period"))
        values.append("(%s::text, %s::vector, %s::text, %s::int)")
        params += [it["id"], ab._vlit(v), it["ticker"], yr]
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
    with db.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: dict[str, list[int]] = {it["id"]: [] for it in items}
    for iid, cid, _ in rows:
        out[iid].append(cid)
    return out


def content_for_strategy(strategy: str) -> dict[int, dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, ticker, year, content FROM chunks_ablation WHERE strategy = %s",
            [strategy],
        ).fetchall()
    return {r[0]: {"id": r[0], "ticker": r[1], "year": r[2], "content": r[3]} for r in rows}


def main() -> None:
    items = ab.load_items(positive_only=True)
    filings = sorted(
        {(it["ticker"], ab._year(it["period"])) for it in items if ab._year(it["period"])}
    )
    print(f"filings: {filings}; building chunks_ablation for {STRATEGIES}...", flush=True)
    setup_table(filings)

    results, variants, chunk_counts = {}, [], {}
    for strategy in STRATEGIES:
        content = content_for_strategy(strategy)
        chunk_counts[strategy] = len(content)
        totals = ab.totals_from_content(items, content)
        ranks = dense_rank_strategy(items, strategy, TOP_K)
        res = ab.eval_variant(
            lambda it, r=ranks, c=content: ab.chunks_from_ids(r[it["id"]], c, TOP_K),
            items, totals,
        )
        results[strategy], _ = res, variants.append((strategy, res["agg"]))

    base = results["fixed"]["agg"]
    sw = results["sentence_window"]["agg"]
    lines = [
        "# Wave 3a — Chunking strategy (fixed vs sentence-window vs parent-doc)",
        "",
        "**Hypothesis.** Sentence-window / parent-doc chunks lift recall@10 over "
        "fixed token chunks by keeping narrative answers intact across boundaries; "
        "if fixed already wins, the corpus is number/table heavy enough that "
        "coherence does not matter.",
        "",
        f"- Filings: {', '.join(f'{t} FY{y}' for t, y in filings)} (10-K), "
        "dense retrieval only.",
        "- Chunk counts: " + ", ".join(f"{s}={chunk_counts[s]}" for s in STRATEGIES) + ".",
        "- Same NVIDIA `nv-embedqa-e5-v5` embeddings; isolated `chunks_ablation` "
        "table (production `chunks` untouched).",
        f"- {len(items)} positive items; recall denominator per strategy = relevant "
        "chunks in that strategy's corpus.",
        "",
        "## Variant comparison (means over positive items)",
        "",
        *ab.comparison_table(variants),
        "",
        f"**Headline.** fixed → sentence_window: {ab.delta_line(base, sw, 'recall@10')}; "
        f"{ab.delta_line(base, sw, 'mrr')}.",
        "",
        "## Theory ↔ Practice",
        "",
        "Fixed-size chunking is the low ceiling Wave 1c flagged: a token window can "
        "cut a sentence — or a number from its label — mid-clause. Sentence-window "
        "chunks respect sentence boundaries with overlap so a claim and its context "
        "stay together; parent-document chunking goes further, embedding a small "
        "precise child for ranking while keeping a larger parent for generation "
        "context. Which wins is corpus-dependent: on dense financial tables the "
        "child/parent split can fragment a table, so the empirical comparison — not "
        "the theory — decides the shipped default.",
    ]
    ab.write_report(REPORT, lines)
    print("NOTE: chunks_ablation left in place for inspection; DROP it when done.", flush=True)


if __name__ == "__main__":
    main()
