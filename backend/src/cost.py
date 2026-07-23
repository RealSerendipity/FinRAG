"""Per-request token → USD cost estimation (Wave 5B).

The primary stack runs on NVIDIA NIM open-weight models (free tier → $0), so the
real $/query is ~0; the table also carries public list prices for the closed
backups so a provider switch produces a meaningful cost line in the eval report
and Langfuse. Prices are USD per 1M tokens as (input, output); unknown models
fall back to $0 rather than guessing.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# USD per 1,000,000 tokens: model -> (input_price, output_price).
# Public list prices, hand-maintained. A model missing from this table is priced
# $0 but *flagged* (see estimate_meter) so a stale table shows up as
# cost_estimated=false in responses instead of silently reading as free.
_PRICES: dict[str, tuple[float, float]] = {
    # NVIDIA NIM open-weight — free tier.
    "meta/llama-3.3-70b-instruct": (0.0, 0.0),
    "nvidia/llama-3.3-nemotron-super-49b-v1": (0.0, 0.0),
    # Closed backups (public list prices, for the $/query comparison only).
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "claude-opus-4-7": (15.0, 75.0),
    "gpt-4o-mini": (0.15, 0.60),
}


def estimate(model: str, usage: dict[str, int]) -> float:
    """Estimate request cost in USD from a usage dict ({input_tokens, output_tokens})."""
    in_price, out_price = _PRICES.get(model, (0.0, 0.0))
    in_tok = usage.get("input_tokens", 0) or 0
    out_tok = usage.get("output_tokens", 0) or 0
    return in_tok / 1_000_000 * in_price + out_tok / 1_000_000 * out_price


def is_known(model: str) -> bool:
    """True when the price table has an entry for `model`."""
    return model in _PRICES


def estimate_meter(meter: dict) -> tuple[float, bool]:
    """Price one request from its meter's per-model usage buckets.

    Returns `(usd, known)`. `known` is False when any model in the request has no
    price entry — those tokens are costed at $0, so the total is a floor rather
    than an estimate; the unknown model is logged so the table gets updated.
    """
    models: dict[str, dict[str, int]] = meter.get("models") or {}
    total = sum(estimate(m, u) for m, u in models.items())
    unknown = sorted(m for m in models if not is_known(m))
    if unknown:
        logger.warning(
            "no price entry for model(s) %s — their tokens are costed at $0",
            ", ".join(unknown),
        )
    return total, not unknown


def cost_details(model: str, usage: dict[str, int]) -> dict[str, float]:
    """Langfuse-shaped cost breakdown ({input, output, total}) in USD."""
    in_price, out_price = _PRICES.get(model, (0.0, 0.0))
    in_usd = (usage.get("input_tokens", 0) or 0) / 1_000_000 * in_price
    out_usd = (usage.get("output_tokens", 0) or 0) / 1_000_000 * out_price
    return {"input": in_usd, "output": out_usd, "total": in_usd + out_usd}
