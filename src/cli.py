"""CLI entry points: finrag ingest and finrag ask.

Usage
-----
  finrag ingest --tickers AAPL,MSFT --year 2024
  finrag ask --ticker AAPL --year 2024 "What was R&D expense?"
"""

from __future__ import annotations

import sys

import click

from src.ingest import ingest as run_ingest
from src.rag import ask as run_ask


@click.group()
def cli() -> None:
    """finrag — SEC filing RAG CLI."""


@cli.command()
@click.option("--tickers", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT")
@click.option("--year", required=True, type=int,
              help="Fiscal year (matched on period-of-report), e.g. 2024")
def ingest(tickers: str, year: int) -> None:
    """Fetch and ingest 10-K filings into the vector store."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise click.UsageError("--tickers must contain at least one ticker symbol")

    failed: list[str] = []
    for ticker in ticker_list:
        click.echo(f"Ingesting {ticker} FY{year}...", nl=False)
        try:
            chunk_count = run_ingest(ticker, year)
            click.echo(f" done ({chunk_count} chunks)")
        except Exception as exc:
            click.echo(f" FAILED: {exc}", err=True)
            failed.append(ticker)

    if failed:
        click.echo(f"\nFailed tickers: {', '.join(failed)}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--ticker", required=True, help="Ticker symbol, e.g. AAPL")
@click.option("--year", default=None, type=int, help="Fiscal year filter (optional)")
@click.argument("question")
def ask(ticker: str, year: int | None, question: str) -> None:
    """Ask a question over ingested filings and print the cited answer."""
    period = f"FY{year}" if year else None
    answer = run_ask(question, ticker=ticker.upper(), period=period)
    click.echo(f"\n{answer.text}\n")
    for citation in answer.citations:
        click.echo(f"  [chunk {citation.chunk_id}] {citation.quote!r}")
