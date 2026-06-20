"""CLI entry points: finrag ingest and finrag ask.

Usage
-----
  finrag ingest --tickers AAPL,MSFT --year 2024
  finrag ingest --tickers AAPL --form-type 10-Q --period 2024-03-29
  finrag ingest --tickers AAPL --form-type 8-K --period 2024-05-10
  finrag ask --ticker AAPL --year 2024 "What was R&D expense?"
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any, Literal

import click
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.db import bootstrap
from src.ingest import VALID_CHUNK_STRATEGIES
from src.ingest import ingest as run_ingest
from src.rag import ask as run_ask

_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,5}$")
_PERIOD_PATTERN = re.compile(r"^(?:FY\d{4}|\d{4}|\d{4}-\d{2}-\d{2})$")


def _normalize_ticker(value: Any) -> str:
    text = str(value).strip().upper()
    if not _TICKER_PATTERN.fullmatch(text):
        raise ValueError("ticker must be 1-5 uppercase alphanumeric characters")
    return text


def _validate_period(value: str | None) -> str | None:
    if value is None:
        return None
    if not _PERIOD_PATTERN.fullmatch(value):
        raise ValueError("period must match FY followed by 4 digits, YYYY, or YYYY-MM-DD")
    return value


class IngestInput(BaseModel):
    """Validated input for the ingest command."""

    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(min_length=1, max_length=5)
    form_type: Literal["10-K", "10-Q", "8-K", "20-F", "DEF 14A"] = "10-K"
    year: int | None = Field(default=None, ge=1994, le=2030)
    period: str | None = None
    chunk_strategy: str | None = None

    @field_validator("chunk_strategy", mode="after")
    @classmethod
    def _validate_chunk_strategy(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_CHUNK_STRATEGIES:
            raise ValueError(f"must be one of {', '.join(VALID_CHUNK_STRATEGIES)}")
        return value

    @field_validator("tickers", mode="before")
    @classmethod
    def _split_tickers(cls, value: Any) -> list[Any]:
        if isinstance(value, str):
            return [item for item in value.split(",") if item.strip()]
        return list(value)

    @field_validator("tickers", mode="after")
    @classmethod
    def _validate_tickers(cls, value: list[str]) -> list[str]:
        return [_normalize_ticker(item) for item in value]

    @field_validator("form_type", mode="before")
    @classmethod
    def _normalize_form_type(cls, value: Any) -> str:
        return str(value).strip().upper()

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
        return _validate_period(value)


class AskInput(BaseModel):
    """Validated input for the ask command."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    year: int | None = Field(default=None, ge=1994, le=2030)
    question: str = Field(min_length=1)

    @field_validator("ticker", mode="before")
    @classmethod
    def _validate_ticker(cls, value: Any) -> str:
        return _normalize_ticker(value)

    @field_validator("question", mode="before")
    @classmethod
    def _normalize_question(cls, value: Any) -> str:
        return str(value).strip()


def _raise_usage_error(exc: ValidationError) -> None:
    messages = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        messages.append(f"{loc}: {error['msg']}")
    raise click.UsageError("; ".join(messages)) from exc


@click.group()
def cli() -> None:
    """finrag — SEC filing RAG CLI."""


@cli.command()
@click.option("--tickers", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT")
@click.option("--form-type", default="10-K", show_default=True,
              help="SEC form code: 10-K, 10-Q, 8-K, 20-F, DEF 14A")
@click.option("--year", default=None, type=int,
              help="Fiscal year (period-of-report), e.g. 2024. Used when --period is omitted.")
@click.option("--period", default=None,
              help="Explicit period string: FY2024, 2024, 2024-03-29. Overrides --year.")
@click.option("--chunk-strategy", default=None, type=click.Choice(VALID_CHUNK_STRATEGIES),
              help="Chunking strategy (default: CHUNK_STRATEGY env, else fixed).")
def ingest(tickers: str, form_type: str, year: int | None, period: str | None,
           chunk_strategy: str | None) -> None:
    """Fetch and ingest SEC filings into the vector store."""
    try:
        parsed = IngestInput(tickers=tickers, form_type=form_type, year=year, period=period,
                             chunk_strategy=chunk_strategy)
    except ValidationError as exc:
        _raise_usage_error(exc)
    if parsed.period is None and parsed.year is None:
        raise click.UsageError("Provide --year or --period")

    bootstrap()
    label = parsed.period or f"FY{parsed.year}"
    failed: list[str] = []
    total_start = time.monotonic()
    for ticker in parsed.tickers:
        click.echo(f"Ingesting {ticker} {parsed.form_type} {label}...", nl=False)
        t0 = time.monotonic()
        try:
            chunk_count = run_ingest(
                ticker,
                form_type=parsed.form_type,
                period=parsed.period,
                fiscal_year=parsed.year,
                chunk_strategy=parsed.chunk_strategy,
            )
            elapsed = time.monotonic() - t0
            click.echo(f" done ({chunk_count} chunks, {elapsed:.1f}s)")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            click.echo(f" FAILED: {exc} ({elapsed:.1f}s)", err=True)
            failed.append(ticker)

    if len(parsed.tickers) > 1:
        click.echo(f"Total: {time.monotonic() - total_start:.1f}s")
    if failed:
        click.echo(f"\nFailed tickers: {', '.join(failed)}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--ticker", required=True, help="Ticker symbol, e.g. AAPL")
@click.option("--year", default=None, type=int, help="Fiscal year filter (optional)")
@click.argument("question")
def ask(ticker: str, year: int | None, question: str) -> None:
    """Ask a question over ingested filings and print the cited answer."""
    try:
        parsed = AskInput(ticker=ticker, year=year, question=question)
    except ValidationError as exc:
        _raise_usage_error(exc)
    bootstrap()
    period = str(parsed.year) if parsed.year else None
    t0 = time.monotonic()
    answer = run_ask(parsed.question, ticker=parsed.ticker, period=period)
    elapsed = time.monotonic() - t0
    click.echo(f"\n{answer.text}\n")
    for citation in answer.citations:
        click.echo(f"  [chunk {citation.chunk_id}] {citation.quote!r}")
    click.echo(f"\n({elapsed:.1f}s)")
