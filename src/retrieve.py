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
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import config, db, obs
from src.embed import embed

logger = logging.getLogger(__name__)

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
_VALID_REWRITES = ("none", "multi_query", "hyde")
_MULTI_QUERY_N = 3  # paraphrases per multi-query expansion


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


def _dense_search(
    embed_text: str, _fts_text: str, conds: list[str], fparams: list, k: int
) -> list[dict]:
    query_vec = embed([embed_text], input_type="query")[0]
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


def _lexical_search(
    _embed_text: str, fts_text: str, conds: list[str], fparams: list, k: int
) -> list[dict]:
    query = fts_text
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


def _hybrid_search(
    embed_text: str, fts_text: str, conds: list[str], fparams: list, k: int
) -> list[dict]:
    """RRF fusion of dense vector and lexical FTS rankings in one SQL round-trip.

    Each ranker contributes 1/(RRF_K + rank); a chunk ranked highly by either
    ranker surfaces, and chunks ranked by both add their contributions. embed_text
    drives the vector side, fts_text the lexical side (they differ only under HyDE).
    """
    query = fts_text
    query_vec = embed([embed_text], input_type="query")[0]
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


def _rrf_fuse(rank_lists: list[list[dict]]) -> list[dict]:
    """RRF-fuse several ranked chunk-dict lists into one ranked list, by chunk id."""
    scores: dict[int, float] = {}
    by_id: dict[int, dict] = {}
    for chunks in rank_lists:
        for rank, c in enumerate(chunks, start=1):
            scores[c["id"]] = scores.get(c["id"], 0.0) + 1.0 / (RRF_K + rank)
            by_id[c["id"]] = c
    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)
    out = []
    for i in ranked:
        item = dict(by_id[i])
        item["rrf"] = scores[i]
        out.append(item)
    return out


def retrieve(
    query: str,
    *,
    ticker: str | None = None,
    period: str | None = None,
    top_k: int = 5,
    mode: str | None = None,
    rerank: bool | None = None,
    candidates: int | None = None,
    rewrite: str | None = None,
) -> list[dict]:
    """Return top-k chunks for a query.

    mode: dense | lexical | hybrid (defaults to RETRIEVAL_MODE env).
    rerank: re-order a larger candidate pool down to top_k (defaults to
            RERANK_ENABLED env). candidates sets the pool size.
    rewrite: none | multi_query | hyde (defaults to QUERY_REWRITE env). multi_query
            issues several LLM paraphrases and RRF-fuses their results; hyde embeds
            an LLM-written hypothetical answer instead of the question (FTS and the
            reranker still use the original query). Wave 3e.
    Each returned dict has keys: id, content, section, chunk_index, metadata,
    plus a score key (distance / score / rrf).
    """
    input_data = RetrieveInput(query=query, ticker=ticker, period=period, top_k=top_k)
    mode = (mode or config.retrieval_mode()).lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown retrieval mode {mode!r}; expected one of {_VALID_MODES}")
    rewrite = (rewrite or config.query_rewrite_mode()).lower()
    if rewrite not in _VALID_REWRITES:
        raise ValueError(f"Unknown query rewrite {rewrite!r}; expected one of {_VALID_REWRITES}")
    do_rerank = config.rerank_enabled() if rerank is None else rerank
    pool = (candidates or config.rerank_candidates()) if do_rerank else input_data.top_k

    with obs.span(
        "retrieve",
        as_type="retriever",
        input=input_data.query,
        metadata={
            "mode": mode, "rewrite": rewrite, "rerank": do_rerank,
            "ticker": input_data.ticker, "period": input_data.period, "top_k": input_data.top_k,
        },
    ) as sp:
        # Multi-query: expand to paraphrases, retrieve each (no further rewrite), fuse.
        if rewrite == "multi_query":
            from src.query_rewrite import multi_query as _gen_multi

            variants = _gen_multi(input_data.query, n=_MULTI_QUERY_N)
            lists = [
                retrieve(v, ticker=ticker, period=period, top_k=pool, mode=mode,
                         rerank=False, rewrite="none")
                for v in variants
            ]
            results = _rrf_fuse(lists)
        else:
            # HyDE swaps only the text that gets embedded; FTS keeps the real query.
            embed_text = input_data.query
            if rewrite == "hyde":
                from src.query_rewrite import hyde as _gen_hyde

                embed_text = _gen_hyde(input_data.query)
            conds, fparams = _filter_conditions(input_data)
            results = _SEARCH[mode](embed_text, input_data.query, conds, fparams, pool)
            # HNSW applies WHERE filters AFTER the index scan, so a selective
            # ticker/period filter can starve the vector result set as the corpus
            # grows. `hnsw.iterative_scan` (set in db._configure) mitigates it on
            # pgvector >= 0.8; this warning makes any residual shortfall visible
            # instead of silently degrading recall.
            if conds and mode in ("dense", "hybrid") and len(results) < input_data.top_k:
                logger.warning(
                    "filtered %s retrieval returned %d/%d chunks (ticker=%s period=%s) — "
                    "possible HNSW post-filter starvation or sparse corpus",
                    mode, len(results), input_data.top_k,
                    input_data.ticker, input_data.period,
                )

        if do_rerank and results:
            # Imported lazily — reranking is an optional service path. Always rerank
            # against the ORIGINAL query, never a HyDE/paraphrase.
            from src.rerank import rerank as rerank_passages

            results = rerank_passages(input_data.query, results, top_k=input_data.top_k)

        results = results[: input_data.top_k]
        sp.update(output={"chunk_ids": [c["id"] for c in results], "count": len(results)})
        return results
