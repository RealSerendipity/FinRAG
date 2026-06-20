"""Retrieval over the chunks table: dense / lexical / hybrid, with optional rerank.

Public surface
--------------
- `retrieve(query, *, ticker, period, top_k, mode, rerank, candidates)` — list of chunk dicts

`mode` selects the candidate generator (dense vector, lexical FTS, or hybrid RRF
fusion of the two). `rerank` re-orders a larger candidate pool down to `top_k`
with a cross-encoder. All three default to the env-configured values
(`RETRIEVAL_MODE`, `RERANK_ENABLED`, `RERANK_CANDIDATES`) so `run_eval` and the
CLI pick up a configured improvement without code changes; explicit kwargs let
the Wave 3 ablation scripts A/B a single variable.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import config, db
from src.embed import embed

_PERIOD_PATTERN = re.compile(r"^(?:FY\d{4}|\d{4}|\d{4}-\d{2}-\d{2})$")

# Reciprocal Rank Fusion constant (Cormack 2009). Dampens the influence of any
# single ranker's top positions; 60 is the value from the original paper.
RRF_K = 60

# Minimum per-ranker candidate depth for hybrid fusion. Each ranker must surface
# enough candidates for RRF to have material to fuse, independent of final top_k.
HYBRID_CANDIDATES = 50

# Postgres `plainto_tsquery` ANDs every term, which is far too strict for QA-style
# queries (the answer token rarely co-occurs with all question words). We rewrite
# the query to OR semantics so FTS ranks chunks by how many query terms they
# match — the retrieval-appropriate behavior.
_OR_TSQUERY = "replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery"

_VALID_MODES = ("dense", "lexical", "hybrid")


class RetrieveInput(BaseModel):
    """Validated input for retrieval."""

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


def _filter_conditions(input_data: RetrieveInput) -> tuple[list[str], list]:
    """Build SQL WHERE fragments (against aliases co/d) and their bind params."""
    conds: list[str] = []
    params: list = []
    if input_data.ticker:
        conds.append("co.ticker = %s")
        params.append(input_data.ticker)
    if input_data.period:
        # period is a DATE column; year-level expands to a range, exact date matches equality.
        yr = _year_from_period(input_data.period)
        if yr is not None:
            conds.append("d.period >= %s AND d.period < %s")
            params.extend([datetime.date(yr, 1, 1), datetime.date(yr + 1, 1, 1)])
        else:
            conds.append("d.period = %s")
            params.append(datetime.date.fromisoformat(input_data.period))
    return conds, params


def _row_to_dict(row: tuple, score_key: str) -> dict:
    return {
        "id": row[0],
        "content": row[1],
        "section": row[2],
        "chunk_index": row[3],
        "metadata": row[4],
        score_key: row[5],
    }


def _dense_search(query: str, conds: list[str], fparams: list, k: int) -> list[dict]:
    query_vec = embed([query], input_type="query")[0]
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    sql = f"""
        SELECT c.id, c.content, c.section, c.chunk_index, c.metadata,
               c.embedding <=> %s::vector AS distance
        FROM chunks c
        JOIN documents d  ON c.document_id = d.id
        JOIN companies co ON d.company_id  = co.id
        {where}
        ORDER BY distance
        LIMIT %s
    """
    params = [query_vec, *fparams, k]
    rows = db.query(sql, params)
    return [_row_to_dict(r, "distance") for r in rows]


def _lexical_search(query: str, conds: list[str], fparams: list, k: int) -> list[dict]:
    extra = (" AND " + " AND ".join(conds)) if conds else ""
    sql = f"""
        WITH qq AS (SELECT {_OR_TSQUERY} AS tsq)
        SELECT c.id, c.content, c.section, c.chunk_index, c.metadata,
               ts_rank_cd(c.tsv, qq.tsq) AS score
        FROM chunks c
        JOIN documents d  ON c.document_id = d.id
        JOIN companies co ON d.company_id  = co.id,
             qq
        WHERE c.tsv @@ qq.tsq{extra}
        ORDER BY score DESC
        LIMIT %s
    """
    params = [query, *fparams, k]
    rows = db.query(sql, params)
    return [_row_to_dict(r, "score") for r in rows]


def _hybrid_search(query: str, conds: list[str], fparams: list, k: int) -> list[dict]:
    """RRF fusion of dense vector and lexical FTS rankings in one SQL round-trip.

    Each ranker contributes 1/(RRF_K + rank); a chunk ranked highly by either
    ranker surfaces, and chunks ranked by both add their contributions.
    """
    query_vec = embed([query], input_type="query")[0]
    cand = max(k, HYBRID_CANDIDATES)  # per-ranker pool depth before fusion
    vec_where = ("WHERE " + " AND ".join(conds)) if conds else ""
    fts_extra = (" AND " + " AND ".join(conds)) if conds else ""
    sql = f"""
        WITH qq AS (SELECT {_OR_TSQUERY} AS tsq),
        vec AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY dist) AS rnk
            FROM (
                SELECT c.id, c.embedding <=> %s::vector AS dist
                FROM chunks c
                JOIN documents d  ON c.document_id = d.id
                JOIN companies co ON d.company_id  = co.id
                {vec_where}
                ORDER BY dist
                LIMIT %s
            ) v
        ),
        fts AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY score DESC) AS rnk
            FROM (
                SELECT c.id, ts_rank_cd(c.tsv, qq.tsq) AS score
                FROM chunks c
                JOIN documents d  ON c.document_id = d.id
                JOIN companies co ON d.company_id  = co.id,
                     qq
                WHERE c.tsv @@ qq.tsq{fts_extra}
                ORDER BY score DESC
                LIMIT %s
            ) f
        ),
        fused AS (
            SELECT COALESCE(vec.id, fts.id) AS id,
                   COALESCE(1.0 / (%s + vec.rnk), 0)
                 + COALESCE(1.0 / (%s + fts.rnk), 0) AS rrf
            FROM vec FULL OUTER JOIN fts ON vec.id = fts.id
        )
        SELECT c.id, c.content, c.section, c.chunk_index, c.metadata, fused.rrf
        FROM fused
        JOIN chunks c ON c.id = fused.id
        ORDER BY fused.rrf DESC
        LIMIT %s
    """
    params = [
        query,                    # qq (OR tsquery)
        query_vec, *fparams, cand,  # vec inner
        *fparams, cand,           # fts inner
        RRF_K, RRF_K,             # fusion
        k,                        # final limit
    ]
    rows = db.query(sql, params)
    return [_row_to_dict(r, "rrf") for r in rows]


_SEARCH = {"dense": _dense_search, "lexical": _lexical_search, "hybrid": _hybrid_search}


def retrieve(
    query: str,
    *,
    ticker: str | None = None,
    period: str | None = None,
    top_k: int = 5,
    mode: str | None = None,
    rerank: bool | None = None,
    candidates: int | None = None,
) -> list[dict]:
    """Return top-k chunks for a query.

    mode: dense | lexical | hybrid (defaults to RETRIEVAL_MODE env).
    rerank: re-order a larger candidate pool down to top_k (defaults to
            RERANK_ENABLED env). candidates sets the pool size.
    Each returned dict has keys: id, content, section, chunk_index, metadata,
    plus a score key (distance / score / rrf).
    """
    input_data = RetrieveInput(query=query, ticker=ticker, period=period, top_k=top_k)
    mode = (mode or config.retrieval_mode()).lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown retrieval mode {mode!r}; expected one of {_VALID_MODES}")
    do_rerank = config.rerank_enabled() if rerank is None else rerank
    pool = (candidates or config.rerank_candidates()) if do_rerank else input_data.top_k

    conds, fparams = _filter_conditions(input_data)
    results = _SEARCH[mode](input_data.query, conds, fparams, pool)

    if do_rerank and results:
        # Imported lazily — reranking is an optional service path.
        from src.rerank import rerank as rerank_passages

        results = rerank_passages(input_data.query, results, top_k=input_data.top_k)

    return results[: input_data.top_k]
