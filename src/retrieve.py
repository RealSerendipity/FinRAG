"""Dense retrieval over the chunks table.

Public surface
--------------
- `retrieve(query, *, ticker, period, top_k)` — returns list of chunk dicts
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import db
from src.embed import embed

_PERIOD_PATTERN = re.compile(r"^(?:FY\d{4}|\d{4}|\d{4}-\d{2}-\d{2})$")


class RetrieveInput(BaseModel):
    """Validated input for dense retrieval."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    ticker: str | None = None
    period: str | None = None
    top_k: int = Field(default=5, ge=1, le=1000)

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, value: Any) -> str:
        if value is None:
            return ""  # min_length=1 will reject this
        return str(value).strip()

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().upper()
        return text or None

    @field_validator("period", mode="before")
    @classmethod
    def _normalize_period(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("period", mode="after")
    @classmethod
    def _validate_period(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _PERIOD_PATTERN.fullmatch(value):
            raise ValueError("period must match FY followed by 4 digits, YYYY, or YYYY-MM-DD")
        if len(value) == 10:
            datetime.date.fromisoformat(value)
        return value


def _year_from_period(period: str) -> int | None:
    if period.startswith("FY"):
        return int(period[2:])
    if len(period) == 4 and period.isdigit():
        return int(period)
    return None


def retrieve(
    query: str,
    *,
    ticker: str | None = None,
    period: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Return top-k chunks most similar to query.

    Filters by ticker and/or period when provided.
    Each returned dict has keys: id, content, section, chunk_index, metadata.
    """
    input_data = RetrieveInput(query=query, ticker=ticker, period=period, top_k=top_k)
    query_vec = embed([input_data.query], input_type="query")[0]

    filters: list[str] = []
    filter_params: list = []

    if input_data.ticker:
        filters.append("co.ticker = %s")
        filter_params.append(input_data.ticker)
    if input_data.period:
        # period is a DATE column; convert the caller's string to typed date objects.
        # A year-level period expands to a date range; YYYY-MM-DD does an exact match.
        yr = _year_from_period(input_data.period)
        if yr is not None:
            filters.append("d.period >= %s AND d.period < %s")
            filter_params.extend([datetime.date(yr, 1, 1), datetime.date(yr + 1, 1, 1)])
        else:
            filters.append("d.period = %s")
            filter_params.append(datetime.date.fromisoformat(input_data.period))

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    # params order: query_vec first (for <=>), then filter values, then top_k (for LIMIT).
    params: list = [query_vec, *filter_params, input_data.top_k]

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
