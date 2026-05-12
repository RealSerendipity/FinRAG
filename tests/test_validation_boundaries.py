"""Boundary validation tests for external inputs."""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from pydantic import ValidationError


def test_settings_parse_comma_separated_model_lists() -> None:
    from src import config

    settings = config.Settings(
        GEMINI_MODELS="gemini-2.5-flash, gemini-2.5-pro",
        OPENAI_MODELS=["gpt-4.1-mini"],
        EMBEDDING_DIM="2048",
    )

    assert settings.GEMINI_MODELS == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert settings.OPENAI_MODELS == ["gpt-4.1-mini"]
    assert settings.EMBEDDING_DIM == 2048


def test_config_helpers_use_current_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import config

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_MODELS", "gpt-4.1-mini,gpt-4.1")
    assert config.llm_model() == "gpt-4.1-mini"

    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    with pytest.raises(ValueError, match="not valid for provider"):
        config.llm_model()


@pytest.mark.parametrize(
    ("env_var", "helper_name"),
    [
        ("EMBEDDING_MODEL", "embedding_model"),
        ("EMBEDDING_DIM", "embedding_dim"),
        ("NVIDIA_BASE_URL", "nvidia_base_url"),
    ],
)
def test_config_helpers_require_env_owned_defaults(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    helper_name: str,
) -> None:
    from src import config

    monkeypatch.delenv(env_var, raising=False)
    helper = getattr(config, helper_name)

    with pytest.raises(RuntimeError, match=f"{env_var} is not set"):
        helper()


@pytest.mark.parametrize(
    ("env_var", "helper_name"),
    [
        ("EMBEDDING_MODEL", "embedding_model"),
        ("EMBEDDING_DIM", "embedding_dim"),
        ("NVIDIA_BASE_URL", "nvidia_base_url"),
    ],
)
def test_config_helpers_reject_blank_env_owned_defaults(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    helper_name: str,
) -> None:
    from src import config

    monkeypatch.setenv(env_var, " ")
    helper = getattr(config, helper_name)

    with pytest.raises(RuntimeError, match=f"{env_var} is not set"):
        helper()


def test_cli_input_models_normalize_and_reject_invalid_values() -> None:
    from src.cli import AskInput, IngestInput

    ingest_input = IngestInput(
        tickers=["aapl", "msft"],
        form_type="10-K",
        year=2024,
        period=None,
    )

    assert ingest_input.tickers == ["AAPL", "MSFT"]
    assert AskInput(ticker="msft", year=2024, question="  revenue?  ").ticker == "MSFT"

    with pytest.raises(ValidationError):
        IngestInput(tickers=["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META"], form_type="10-K")
    with pytest.raises(ValidationError):
        IngestInput(tickers=["AAPL"], form_type="S-1", period="2024")
    with pytest.raises(ValidationError):
        IngestInput(tickers=["AAPL"], form_type="10-K", period="Q1-2024")
    with pytest.raises(ValidationError):
        AskInput(ticker="TOO-LONG", year=2024, question="revenue?")


def test_edgar_models_parse_dates_and_reject_invalid_company_info() -> None:
    from src.clients.edgar import EdgarCompanyInfo, EdgarFiling

    company = EdgarCompanyInfo.model_validate({"cik": "320193", "name": "Apple Inc."})
    filing = EdgarFiling.model_validate(
        {
            "accession": "0000320193-24-000123",
            "filed_at": "2025-01-31",
            "report_date": "2024-12-31",
            "raw_url": "https://www.sec.gov/Archives/example.txt",
            "text": "Revenue increased.",
        }
    )

    assert company.cik == 320193
    assert filing.filed_at == datetime.date(2025, 1, 31)
    assert filing.report_date == datetime.date(2024, 12, 31)

    with pytest.raises(ValidationError):
        EdgarCompanyInfo.model_validate({"cik": 0, "name": ""})


def test_ingest_validates_edgar_dicts_before_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import ingest

    monkeypatch.setattr(
        ingest,
        "company_info_for_ticker",
        lambda _: {"cik": 320193, "name": "Apple Inc."},
    )
    monkeypatch.setattr(
        ingest,
        "fetch_filing",
        lambda *_: {
            "accession": "0000320193-24-000123",
            "filed_at": "2025-01-31",
            "report_date": "FY2024",
            "raw_url": "https://www.sec.gov/Archives/example.txt",
            "text": "Revenue increased.",
        },
    )
    embed_batched = mock.Mock(side_effect=AssertionError("embedding should not be reached"))
    monkeypatch.setattr(ingest, "_embed_batched", embed_batched)

    with pytest.raises(ValidationError):
        ingest.ingest("AAPL", fiscal_year=2024)
    embed_batched.assert_not_called()


def test_rag_input_validation_runs_before_retrieve(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import rag
    from src.rag import RagAskInput

    assert RagAskInput(question="revenue", period="FY2024").top_k == 5
    retrieve = mock.Mock(side_effect=AssertionError("retrieve should not be reached"))
    monkeypatch.setattr(rag, "retrieve", retrieve)

    with pytest.raises(ValidationError):
        rag.ask("", ticker="AAPL")
    retrieve.assert_not_called()


def test_retrieve_input_validation_runs_before_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import retrieve
    from src.retrieve import RetrieveInput

    assert RetrieveInput(query="revenue", period="2024").top_k == 5
    embed = mock.Mock(side_effect=AssertionError("embedding should not be reached"))
    monkeypatch.setattr(retrieve, "embed", embed)

    with pytest.raises(ValidationError):
        retrieve.retrieve("")
    with pytest.raises(ValidationError):
        retrieve.retrieve("revenue", top_k=1001)
    embed.assert_not_called()
