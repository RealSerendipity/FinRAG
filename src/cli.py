"""CLI entry points: finrag ingest and finrag ask.

Usage
-----
  finrag ingest --tickers AAPL,MSFT --year 2024
  finrag ask --ticker AAPL --year 2024 "What was R&D expense?"
"""

from __future__ import annotations

import click

from src.ingest import ingest as _ingest
from src.rag import ask as _ask


@click.group()
def cli() -> None:
    """finrag — SEC filing RAG CLI."""


@cli.command()
@click.option("--tickers", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT")
@click.option("--year", required=True, type=int, help="Calendar year of filing, e.g. 2024")
def ingest(tickers: str, year: int) -> None:
    """Fetch and ingest 10-K filings into the vector store."""
    for ticker in [t.strip().upper() for t in tickers.split(",") if t.strip()]:
        click.echo(f"Ingesting {ticker} {year}...", nl=False)
        n = _ingest(ticker, year)
        click.echo(f" done ({n} chunks)")


@cli.command()
@click.option("--ticker", required=True, help="Ticker symbol, e.g. AAPL")
@click.option("--year", default=None, type=int, help="Fiscal year filter (optional)")
@click.argument("question")
def ask(ticker: str, year: int | None, question: str) -> None:
    """Ask a question over ingested filings and print the cited answer."""
    period = f"FY{year}" if year else None
    answer = _ask(question, ticker=ticker.upper(), period=period)
    click.echo(f"\n{answer.text}\n")
    for c in answer.citations:
        click.echo(f"  [chunk {c.chunk_id}] {c.quote!r}")
