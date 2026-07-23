"""retrieve_filing tool — semantic search over ingested SEC filing text.

Thin wrapper over `src.retrieve.retrieve` (hybrid + rerank, per env config) for
narrative / qualitative questions ("what risks did Apple cite?"). Numeric facts
should go through lookup_metric instead — that hits structured XBRL, not chunked
prose. Returns chunk_id-tagged excerpts so the agent can quote and cite them.
"""

from __future__ import annotations

from src.retrieve import retrieve

from .spec import Tool

_MAX_CHARS = 600  # per-chunk excerpt cap kept in the observation
_TOP_K = 5


def retrieve_filing(query: str, ticker: str | None = None, year: int | str | None = None) -> str:
    """Retrieve top filing chunks for a query, optionally filtered by ticker/year."""
    period = str(year) if year not in (None, "") else None
    chunks = retrieve(query, ticker=ticker, period=period, top_k=_TOP_K)
    if not chunks:
        scope = f" for {ticker or 'any ticker'}{f' {period}' if period else ''}"
        return f"No matching filing chunks found{scope}. The filing may not be ingested."
    out = []
    for c in chunks:
        excerpt = " ".join(c["content"].split())[:_MAX_CHARS]
        out.append(f"[chunk_id={c['id']}] {excerpt}")
    return "\n\n".join(out)


TOOL = Tool(
    name="retrieve_filing",
    description="Semantic search over ingested SEC filing text for narrative/qualitative "
    "facts. Returns chunk_id-tagged excerpts to quote. Use lookup_metric for numbers.",
    parameters={
        "query": "natural-language search query",
        "ticker": "optional ticker filter, e.g. 'AAPL'",
        "year": "optional fiscal year filter, e.g. 2024",
    },
    func=retrieve_filing,
)
