"""Wave 3g — section/layout-aware chunking + heading prefix vs fixed.

Hypothesis: splitting a 10-K at its structural headings (Item / Part) so chunks
never span sections, and prefixing each chunk with its section heading, lifts
recall@10 / MRR — the heading gives the chunk embedding the section context a bare
token window loses, and section boundaries keep a topic intact.

Same NVIDIA embeddings, isolated `chunks_ablation` table (production `chunks`
untouched), dense retrieval only (retrieval metrics are LLM-independent). A net
win here is the cue to make `section` the default CHUNK_STRATEGY and confirm
faithfulness with a full run_eval.

Usage: uv run python experiments/wave3_g_section_chunking.py
"""

from __future__ import annotations

from pathlib import Path

import _ablation as ab

from src import db
from src.embed import embed
from src.financial.edgar import fetch_filing
from src.ingest import build_chunks

REPORT = Path(__file__).parent.parent / "eval" / "reports" / "wave_3g.md"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
STRATEGIES = ("fixed", "section")
TOP_K = 10
EMBED_BATCH = 32


def filing_text(ticker: str, year: int) -> str:
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


def setup_table(filings: list[tuple[str, int]]) -> dict[str, int]:
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS chunks_ablation")
        conn.execute(
            "CREATE TABLE chunks_ablation (id BIGSERIAL PRIMARY KEY, strategy TEXT, "
            "ticker TEXT, year INT, content TEXT, embedding VECTOR(1024))"
        )
    counts: dict[str, int] = {}
    for strategy in STRATEGIES:
        total = 0
        for ticker, year in filings:
            records = build_chunks(filing_text(ticker, year), strategy)
            contents = [c for c, _ in records]
            print(f"  {strategy} {ticker} {year}: {len(contents)} chunks, embedding...", flush=True)
            vectors = _embed_all(contents)
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks_ablation (strategy, ticker, year, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s::vector)",
                    [(strategy, ticker, year, c, v)
                     for c, v in zip(contents, vectors, strict=True)],
                )
            total += len(contents)
        counts[strategy] = total
    return counts


def main() -> None:
    items = ab.load_items(positive_only=True)
    filings = sorted(
        {(it["ticker"], ab._year(it["period"])) for it in items if ab._year(it["period"])}
    )
    print(f"filings: {filings}; building chunks_ablation for {STRATEGIES}...", flush=True)
    counts = setup_table(filings)

    results, variants = {}, []
    for strategy in STRATEGIES:
        content = ab.content_for_ablation(strategy)
        totals = ab.totals_from_content(items, content)
        ranks = ab.dense_rank_ablation(items, strategy, TOP_K)
        res = ab.eval_variant(
            lambda it, r=ranks, c=content: ab.chunks_from_ids(r[it["id"]], c, TOP_K),
            items, totals,
        )
        results[strategy], _ = res, variants.append((strategy, res["agg"]))

    base, sec = results["fixed"]["agg"], results["section"]["agg"]
    lines = [
        "# Wave 3g — Section/layout-aware chunking + heading prefix vs fixed",
        "",
        "**Hypothesis.** Splitting at 10-K structural headings (Item / Part) and "
        "prefixing each chunk with its section heading lifts recall@10 / MRR vs "
        "fixed token chunking.",
        "",
        f"- Filings: {', '.join(f'{t} FY{y}' for t, y in filings)} (10-K), dense only.",
        "- Chunk counts: " + ", ".join(f"{s}={counts[s]}" for s in STRATEGIES) + ".",
        "- Same NVIDIA `nv-embedqa-e5-v5` embeddings; isolated `chunks_ablation` table.",
        f"- {len(items)} positive items; recall denominator per strategy = relevant "
        "chunks in that strategy's corpus.",
        "",
        "## Variant comparison (means over positive items)",
        "",
        *ab.comparison_table(variants),
        "",
        f"**Headline.** fixed → section: {ab.delta_line(base, sec, 'recall@10')}; "
        f"{ab.delta_line(base, sec, 'mrr')}; {ab.delta_line(base, sec, 'ndcg@10')}.",
        "",
        "## Theory ↔ Practice",
        "",
        "10-K structure is strong and regular (Item 1 Business, 1A Risk Factors, 7 "
        "MD&A, 8 Financial Statements), so section boundaries are a reliable place to "
        "cut: a chunk stays within one topic instead of straddling two. Prefixing the "
        "section heading injects context the bi-encoder would otherwise miss — a chunk "
        "of raw numbers under 'Item 7. MD&A' now embeds nearer MD&A-style queries. "
        "Both are near-free at ingest. If recall@10 / MRR improve, switch the default "
        "CHUNK_STRATEGY to `section` and confirm faithfulness with a full run_eval; if "
        "flat, fixed already captures the signal on this corpus.",
    ]
    ab.write_report(REPORT, lines)
    print("NOTE: chunks_ablation left in place; DROP it when done.", flush=True)


if __name__ == "__main__":
    main()
