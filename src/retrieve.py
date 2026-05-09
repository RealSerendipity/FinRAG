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

    filters: list[str] = []
    filter_params: list = []

    if ticker:
        filters.append("co.ticker = %s")
        filter_params.append(ticker.upper())
    if period:
        filters.append("d.period = %s")
        filter_params.append(period)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    # params order: query_vec first (for <=>), then filter values, then top_k (for LIMIT).
    params: list = [query_vec, *filter_params, top_k]

    sql = f"""
        SELECT
            c.id,
            c.content,
            c.section,
            c.chunk_index,
            c.metadata,
            c.embedding <=> %s::vector AS distance
        FROM chunks c
        JOIN documents d  ON c.document_id = d.id
        JOIN companies co ON d.company_id  = co.id
        {where}
        ORDER BY distance
        LIMIT %s
    """

    with db.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": row[0],
            "content": row[1],
            "section": row[2],
            "chunk_index": row[3],
            "metadata": row[4],
            "distance": row[5],
        }
        for row in rows
    ]
