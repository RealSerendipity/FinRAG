"""lookup_metric + compare_companies tools — structured financials via SEC XBRL.

Numeric questions ("R&D expense", "total revenue") should not go through RAG over
chunked prose: the audited values live in the SEC XBRL Financial Statements API
as machine-readable facts. These tools resolve a friendly concept name to one or
more us-gaap tags, fetch the company's full reporting history, and select the
annual (10-K, full-year) figure for the requested fiscal year. Both tools share
the concept map, so they live together.

Public surface
--------------
- `LOOKUP_TOOL`, `COMPARE_TOOL` — the registered Tool specs
- `metric_value(ticker, concept, year)` — structured fact, reused by compare + eval
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import httpx

from src.financial import edgar as fin_edgar

from .spec import Tool

# Friendly concept name -> (ordered candidate us-gaap tags, preferred unit).
# Companies tag the same line item differently across filings/eras, so each
# concept lists fallbacks tried in order until one returns data.
_CONCEPTS: dict[str, tuple[list[str], str]] = {
    "revenue": (
        ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
        "USD",
    ),
    "net_sales": (
        ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
        "USD",
    ),
    "net_income": (["NetIncomeLoss"], "USD"),
    "rd_expense": (["ResearchAndDevelopmentExpense"], "USD"),
    "research_and_development": (["ResearchAndDevelopmentExpense"], "USD"),
    "operating_income": (["OperatingIncomeLoss"], "USD"),
    "gross_profit": (["GrossProfit"], "USD"),
    "operating_expenses": (["OperatingExpenses", "CostsAndExpenses"], "USD"),
    "total_assets": (["Assets"], "USD"),
    "total_liabilities": (["Liabilities"], "USD"),
    "cash": (["CashAndCashEquivalentsAtCarryingValue"], "USD"),
    "eps_diluted": (["EarningsPerShareDiluted"], "USD/shares"),
    "eps_basic": (["EarningsPerShareBasic"], "USD/shares"),
}

_MIN_ANNUAL_DAYS = 350  # period length floor that separates annual flows from quarterly


@dataclass(frozen=True)
class MetricFact:
    ticker: str
    concept: str
    tag: str
    unit: str
    value: float
    fiscal_year: int
    period_end: str
    form: str


def _annual_facts(facts: list[dict]) -> list[dict]:
    """Keep only full-year 10-K facts (annual flows + fiscal-year-end instants)."""
    out = []
    for f in facts:
        if not str(f.get("form", "")).startswith("10-K"):
            continue
        start, end = f.get("start"), f.get("end")
        if not end:
            continue
        if start:  # flow fact — drop quarterly / partial periods
            days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
            if days < _MIN_ANNUAL_DAYS:
                continue
        out.append(f)
    return out


def _latest_by_year(facts: list[dict]) -> dict[int, dict]:
    """Map fiscal-year (from period-end) to the most recently filed fact for it."""
    best: dict[int, dict] = {}
    for f in facts:
        year = dt.date.fromisoformat(f["end"]).year
        cur = best.get(year)
        if cur is None or str(f.get("filed", "")) > str(cur.get("filed", "")):
            best[year] = f
    return best


def metric_value(ticker: str, concept: str, year: int | str | None = None) -> MetricFact:
    """Return the annual XBRL fact for a ticker/concept, for `year` or the latest.

    Raises KeyError for an unknown concept, LookupError when no annual fact exists
    (unknown ticker, never-reported tag, or no data for the requested year).
    """
    key = str(concept).strip().lower()
    if key not in _CONCEPTS:
        raise KeyError(
            f"unknown concept {concept!r}. Known: {', '.join(sorted(_CONCEPTS))}"
        )
    tags, unit_pref = _CONCEPTS[key]
    year_int = int(year) if year not in (None, "") else None

    for tag in tags:
        try:
            payload = fin_edgar.company_concept(ticker, tag)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue  # company never reported this tag — try the next candidate
            raise
        units = payload.get("units", {})
        unit = unit_pref if unit_pref in units else next(iter(units), None)
        if not unit:
            continue
        by_year = _latest_by_year(_annual_facts(units[unit]))
        if not by_year:
            continue
        chosen_year = year_int if year_int is not None else max(by_year)
        fact = by_year.get(chosen_year)
        if fact is None:
            continue
        return MetricFact(
            ticker=ticker.upper(),
            concept=key,
            tag=tag,
            unit=unit,
            value=float(fact["val"]),
            fiscal_year=chosen_year,
            period_end=fact["end"],
            form=str(fact.get("form", "")),
        )

    scope = f" for FY{year_int}" if year_int is not None else ""
    raise LookupError(
        f"No annual XBRL value for {ticker.upper()} {key}{scope} "
        f"(tags tried: {', '.join(tags)})"
    )


def _fmt_value(value: float, unit: str) -> str:
    if unit == "USD":
        if abs(value) >= 1e6:
            return f"${value / 1e6:,.0f} million"
        return f"${value:,.2f}"
    if unit == "USD/shares":
        return f"${value:,.2f} per share"
    return f"{value:,.4g} {unit}"


def lookup_metric(ticker: str, concept: str, year: int | str | None = None) -> str:
    """Look up one annual financial metric from SEC XBRL."""
    try:
        fact = metric_value(ticker, concept, year)
    except KeyError as exc:
        return f"Error: {exc}"
    except LookupError as exc:
        return f"Error: {exc}"
    return (
        f"{fact.ticker} {fact.concept} FY{fact.fiscal_year}: "
        f"{_fmt_value(fact.value, fact.unit)} "
        f"(raw {fact.value:.0f} {fact.unit}, us-gaap:{fact.tag}, "
        f"{fact.form}, period ended {fact.period_end})"
    )


def _split_tickers(tickers: list[str] | str) -> list[str]:
    if isinstance(tickers, str):
        return [t.strip() for t in tickers.split(",") if t.strip()]
    return [str(t).strip() for t in tickers if str(t).strip()]


def compare_companies(
    tickers: list[str] | str, concept: str, year: int | str | None = None
) -> str:
    """Look up the same metric for several companies and return them side by side."""
    syms = _split_tickers(tickers)
    if len(syms) < 2:
        return "Error: compare_companies needs at least two tickers"
    lines = []
    for sym in syms:
        try:
            fact = metric_value(sym, concept, year)
            lines.append(
                f"{fact.ticker} FY{fact.fiscal_year} {fact.concept}: "
                f"{_fmt_value(fact.value, fact.unit)} (raw {fact.value:.0f} {fact.unit})"
            )
        except (KeyError, LookupError) as exc:
            lines.append(f"{sym.upper()}: error — {exc}")
    return "\n".join(lines)


LOOKUP_TOOL = Tool(
    name="lookup_metric",
    description="Look up one audited annual financial figure from SEC XBRL "
    f"(no RAG). Concepts: {', '.join(sorted(_CONCEPTS))}.",
    parameters={
        "ticker": "company ticker, e.g. 'NVDA'",
        "concept": "metric name from the supported concept list",
        "year": "fiscal year, e.g. 2024 (omit for the latest)",
    },
    func=lookup_metric,
)

COMPARE_TOOL = Tool(
    name="compare_companies",
    description="Look up the same XBRL metric for two or more companies and "
    "return the values side by side for the same fiscal year.",
    parameters={
        "tickers": "list or comma string of tickers, e.g. ['NVDA','AMD']",
        "concept": "metric name from the supported concept list",
        "year": "fiscal year, e.g. 2024 (omit for the latest)",
    },
    func=compare_companies,
)
