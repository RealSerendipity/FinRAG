"""Wave 3b — table-aware ingestion (Docling) vs fixed chunking.

Hypothesis: extracting tables as independent, serialized chunks recovers numeric
answers that fixed chunking fragments across boundaries — numeric/table-category
recall@10 rises with no change to narrative chunking. If it does not, Docling's
SEC-HTML table extraction is too lossy to help.

Builds a `table_aware` corpus = fixed narrative chunks + serialized table chunks
in the dedicated `chunks_ablation` table (production `chunks` untouched), then
measures dense recall on numeric + table questions.

Usage: uv run python experiments/wave3_b_tables.py
"""

from __future__ import annotations

import json
from pathlib import Path

import _ablation as ab

from src import db
from src.clients import edgar as ec
from src.embed import embed
from src.financial.edgar import cik_for_ticker
from src.financial.table_extract import extract_tables
from src.ingest import chunk_text

REPORT = Path(__file__).parent.parent / "eval" / "reports" / "wave_3b.md"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
TOP_K = 10
EMBED_BATCH = 32
FOCUS = ("numeric", "table")


def raw_html(ticker: str, year: int) -> Path | None:
    """Return a 10-K's raw HTML path, fetching to data/raw if not cached.

    Returns None if the filing HTML is neither cached nor fetchable (EDGAR is
    network-flaky); the caller skips that filing and the report notes the gap.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{ticker}_{year}_10-K.html"
    if path.exists():
        return path
    try:
        cik = cik_for_ticker(ticker)
        rec = json.loads(ec.get_submissions(cik))["filings"]["recent"]
        idx = next(
            i for i, f in enumerate(rec["form"])
            if f == "10-K" and rec["reportDate"][i].startswith(str(year))
        )
        acc = rec["accessionNumber"][idx].replace("-", "")
        raw = ec.get_document(cik, acc, rec["primaryDocument"][idx])
        path.write_bytes(raw)
        return path
    except Exception as exc:
        print(f"  WARN: could not fetch {ticker} FY{year} HTML ({type(exc).__name__}); skipping",
              flush=True)
        return None


def _embed_all(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        out.extend(embed(texts[i : i + EMBED_BATCH], input_type="passage"))
    return out


def build_table_aware(filings: list[tuple[str, int]]) -> dict[str, int]:
    """Create the table_aware strategy: copy fixed narrative + add serialized tables.

    Rebuilt from scratch each run (cheap) so a partially-built corpus never lingers.
    Long tables are split by rows under the embedder's 512-token limit.
    """
    with db.get_conn() as conn:
        conn.execute("DELETE FROM chunks_ablation WHERE strategy = 'table_aware'")
        # Start from the fixed narrative chunks (3a must have populated 'fixed').
        conn.execute(
            "INSERT INTO chunks_ablation (strategy, ticker, year, content, embedding) "
            "SELECT 'table_aware', ticker, year, content, embedding "
            "FROM chunks_ablation WHERE strategy = 'fixed'"
        )
    covered: list[tuple[str, int]] = []
    for ticker, year in filings:
        html = raw_html(ticker, year)
        if html is None:
            continue
        tables = extract_tables(html)
        # Split oversized tables into row-groups under the 512-token embed limit.
        pieces = [p for t in tables for p in chunk_text(t, max_tokens=250)]
        print(f"  {ticker} {year}: {len(tables)} tables -> {len(pieces)} chunks, embedding...",
              flush=True)
        vectors = _embed_all(pieces)
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks_ablation (strategy, ticker, year, content, embedding) "
                "VALUES ('table_aware', %s, %s, %s, %s::vector)",
                [(ticker, year, t, v) for t, v in zip(pieces, vectors, strict=True)],
            )
        covered.append((ticker, year))
    build_table_aware.covered = covered  # type: ignore[attr-defined]
    counts = {}
    with db.get_conn() as conn:
        for s in ("fixed", "table_aware"):
            counts[s] = conn.execute(
                "SELECT count(*) FROM chunks_ablation WHERE strategy=%s", [s]
            ).fetchone()[0]
    return counts


def _measure(items: list[dict], strategy: str) -> dict:
    content = ab.content_for_ablation(strategy)
    totals = ab.totals_from_content(items, content)
    ranks = ab.dense_rank_ablation(items, strategy, TOP_K)
    return ab.eval_variant(
        lambda it: ab.chunks_from_ids(ranks[it["id"]], content, TOP_K), items, totals
    )


def main() -> None:
    all_items = ab.load_items(positive_only=True)
    focus_items = [it for it in all_items if it["category"] in FOCUS]
    filings = sorted(
        {(it["ticker"], ab._year(it["period"])) for it in all_items if ab._year(it["period"])}
    )
    print(f"filings: {filings}; building table_aware corpus...", flush=True)
    counts = build_table_aware(filings)
    covered = getattr(build_table_aware, "covered", filings)

    # numeric + table focus, plus the full set for context.
    res_focus = {s: _measure(focus_items, s) for s in ("fixed", "table_aware")}
    res_all = {s: _measure(all_items, s) for s in ("fixed", "table_aware")}

    fb, tb = res_focus["fixed"]["agg"], res_focus["table_aware"]["agg"]
    lines = [
        "# Wave 3b — Table-aware ingestion (Docling) vs fixed chunking",
        "",
        "**Hypothesis.** Serializing tables as independent chunks recovers numeric "
        "answers fixed chunking fragments; numeric/table recall@10 rises. If not, "
        "Docling's SEC-HTML table extraction is too lossy to help.",
        "",
        f"- Filings: {', '.join(f'{t} FY{y}' for t, y in filings)} (10-K raw HTML).",
        "- Table coverage this run: "
        + (", ".join(f"{t} FY{y}" for t, y in covered) if covered else "NONE")
        + (" (others' HTML unavailable — EDGAR network-flaky — so those years keep "
           "narrative-only chunks)" if len(covered) < len(filings) else ""),
        f"- Corpus chunk counts: fixed={counts['fixed']}, "
        f"table_aware={counts['table_aware']} (fixed narrative + serialized tables).",
        "- Table extraction: Docling HTML backend → compact 'label | value' rows, "
        "tables with < 3 numbers dropped.",
        f"- Focus set: numeric + table questions ({len(focus_items)} items); "
        f"full set = {len(all_items)} items. Dense retrieval only.",
        "",
        "## numeric + table questions",
        "",
        *ab.comparison_table([("fixed", fb), ("table_aware", tb)]),
        "",
        f"**Headline (numeric+table).** {ab.delta_line(fb, tb, 'recall@10')}; "
        f"{ab.delta_line(fb, tb, 'mrr')}; {ab.delta_line(fb, tb, 'recall@5')}.",
        "",
        "## full question set (regression check)",
        "",
        *ab.comparison_table([("fixed", res_all["fixed"]["agg"]),
                              ("table_aware", res_all["table_aware"]["agg"])]),
        "",
        "## Theory ↔ Practice",
        "",
        "A table is a 2-D structure; linearizing a 10-K to text (Wave 1c) destroys "
        "the row-label/column-header binding that makes a cell meaningful, so a "
        "fixed window can keep '391,035' while losing 'total net sales'. Extracting "
        "tables as units and serializing each as 'label | value' rows restores that "
        "binding inside a single chunk. The practical limiter is extraction "
        "fidelity: SEC HTML nests formatting tables heavily, and an extractor built "
        "for clean documents recovers cells unevenly — so the measured delta, not "
        "the premise, decides whether table-aware ingestion earns its dependency.",
    ]
    ab.write_report(REPORT, lines)


if __name__ == "__main__":
    main()
