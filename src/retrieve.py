"""Dense retrieval over the chunks table.

Public surface
--------------
- `retrieve(query, *, ticker, period, top_k)` — returns list of chunk dicts
"""

from __future__ import annotations

from src import config, db
from src.embed import embed


def retrieve(
    query: str,
    *,
    ticker: str | None = None,
    period: str | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Return top-k chunks most similar to query.

    Filters by ticker and/or period when provided.
    Each returned dict has keys: id, content, section, chunk_index, metadata.
    """
    query_vec = embed([query], input_type="query")[0]

    # Build optional WHERE clause for metadata filters.
    filters: list[str] = []
    params: list = [query_vec, top_k]

    if ticker:
        filters.append("d.ticker = %s")
        params.insert(len(params) - 1, ticker)
    if period:
        filters.append("d.period = %s")
        params.insert(len(params) - 1, period)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    # params order: [query_vec, *filter_values, top_k]
    # Rebuild with correct order: query_vec first for the <=> operator, top_k last for LIMIT.
    ordered_params: list = [query_vec] + [p for p in params if p not in (query_vec, top_k)] + [top_k]

    sql = f"""
        SELECT
            c.id,
            c.content,
            c.section,
            c.chunk_index,
            c.metadata,
            c.embedding <=> %s::vector AS distance
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        {where}
        ORDER BY distance
        LIMIT %s
    """

    with db.get_conn() as conn:
        rows = conn.execute(sql, ordered_params).fetchall()

    return [
        {
            "id": r[0],
            "content": r[1],
            "section": r[2],
            "chunk_index": r[3],
            "metadata": r[4],
            "distance": r[5],
        }
        for r in rows
    ]
