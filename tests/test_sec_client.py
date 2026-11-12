"""Offline unit tests for FinovaLabs SEC EDGAR client, caching, retries, and DB persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from finova_labs.audit import verify_audit_chain
from finova_labs.database import fetch_filing_metadata, init_db
from finova_labs.exceptions import ConfigurationError, SecClientError
from finova_labs.sec_client import SecEdgarClient, normalize_cik
from finova_labs.settings import Settings, resolve_sec_user_agent


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    json_error: bool = False,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if json_error:
        resp.json.side_effect = ValueError("Invalid JSON")
    else:
        resp.json.return_value = json_data
    return resp


def _sample_tickers_payload() -> dict[str, Any]:
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }


def _sample_submissions_payload() -> dict[str, Any]:
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-25-000010",
                    "0000320193-24-000123",
                    "0000320193-23-000106",
                ],
                "filingDate": ["2025-02-01", "2024-11-01", "2023-11-03"],
                "reportDate": ["2024-12-28", "2024-09-28", "2023-09-30"],
                "form": ["10-Q", "10-K", "10-K"],
                "primaryDocument": [
                    "aapl-20241228.htm",
                    "aapl-20240928.htm",
                    "aapl-20230930.htm",
                ],
                "primaryDocDescription": ["10-Q", "10-K", "10-K"],
            },
            "files": [],
        },
    }


def _sample_company_facts_payload() -> dict[str, Any]:
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {"USD": [{"val": 391035000000, "fy": 2024, "form": "10-K"}]},
                }
            }
        },
    }


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        sec={
            "user_agent": "FinovaLabs contact@example.com",
            "cache_dir": str(tmp_path / "cache" / "sec"),
            "request_timeout_seconds": 10,
            "max_requests_per_second": 5,
        },
    )


def test_user_agent_rejects_placeholder_and_uses_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder domains are rejected unless a legitimate email is configured via env."""
    monkeypatch.delenv("FINOVALABS_SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("FINOVALABS_SEC_CONTACT_EMAIL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(ConfigurationError):
        resolve_sec_user_agent(settings, require_real_email=True)

    monkeypatch.setenv("FINOVALABS_SEC_CONTACT_EMAIL", "auditor@finovalabs.ai")
    ua = resolve_sec_user_agent(settings, require_real_email=True)
    assert ua == "FinovaLabs auditor@finovalabs.ai"


def test_normalize_cik_valid_and_invalid() -> None:
    """CIK normalization zero-pads to 10 digits and rejects non-numeric inputs."""
    assert normalize_cik(320193) == "0000320193"
    assert normalize_cik("CIK320193") == "0000320193"
    with pytest.raises(SecClientError):
        normalize_cik("ABC")


def test_end_to_end_10k_bundle_caching_and_persistence(tmp_path: Path) -> None:
    """Client resolves ticker -> CIK -> latest 10-K -> Company Facts, caches, and persists."""
    settings = _build_settings(tmp_path)
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = [
        _make_response(200, _sample_tickers_payload()),
        _make_response(200, _sample_submissions_payload()),
        _make_response(200, _sample_company_facts_payload()),
    ]

    client = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs analyst@finovalabs.ai",
        session=session,
        sleep_fn=lambda _: None,
    )

    db_file = tmp_path / "test_sec.db"
    init_db(db_file)

    bundle = client.fetch_latest_10k_bundle("aapl", persist=True, db_path=db_file)
    assert bundle.company.cik == "0000320193"
    assert bundle.company.ticker == "AAPL"
    assert bundle.latest_10k.form_type == "10-K"
    assert bundle.latest_10k.accession_number == "0000320193-24-000123"
    assert bundle.latest_10k.filing_date == "2024-11-01"
    assert bundle.latest_10k.reporting_period == "2024-09-28"
    assert (
        bundle.latest_10k.filing_url
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )
    assert bundle.latest_10k.submissions_url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert (
        bundle.latest_10k.companyfacts_url
        == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    )
    assert "us-gaap" in bundle.company_facts.facts
    assert session.get.call_count == 3

    # Verify SQLite persistence and audit chain entry
    stored = fetch_filing_metadata(cik="0000320193", form_type="10-K", db_path=db_file)
    assert len(stored) == 1
    assert stored[0]["accession_number"] == "0000320193-24-000123"
    assert stored[0]["reporting_period"] == "2024-09-28"
    is_valid, count, _ = verify_audit_chain(db_file)
    assert is_valid is True and count == 1

    # Second call must hit local disk cache with zero additional HTTP calls
    bundle_cached = client.fetch_latest_10k_bundle("AAPL", persist=False)
    assert session.get.call_count == 3
    assert bundle_cached.company.from_cache is True
    assert bundle_cached.company_facts.from_cache is True


def test_retries_on_rate_limit_and_errors(tmp_path: Path) -> None:
    """Client retries HTTP 429 and cleanly raises SecClientError on 403/timeout/malformed JSON."""
    settings = _build_settings(tmp_path)
    sleeps: list[float] = []
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = [
        _make_response(429, headers={"Retry-After": "1"}),
        _make_response(200, _sample_tickers_payload()),
    ]

    client = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs analyst@finovalabs.ai",
        session=session,
        sleep_fn=sleeps.append,
    )
    company = client.lookup_company_by_ticker("MSFT")
    assert company.cik == "0000789019"
    assert 1.0 in sleeps

    # HTTP 403 User-Agent error
    session_403 = MagicMock(spec=requests.Session)
    session_403.headers = {}
    session_403.get.return_value = _make_response(403)
    client_403 = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs analyst@finovalabs.ai",
        session=session_403,
        sleep_fn=lambda _: None,
    )
    with pytest.raises(SecClientError, match="HTTP 403"):
        client_403.lookup_company_by_ticker("AAPL", force_refresh=True)

    # Malformed JSON
    session_bad = MagicMock(spec=requests.Session)
    session_bad.headers = {}
    session_bad.get.return_value = _make_response(200, json_error=True)
    client_bad = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs analyst@finovalabs.ai",
        session=session_bad,
        sleep_fn=lambda _: None,
    )
    with pytest.raises(SecClientError, match="Malformed JSON"):
        client_bad.lookup_company_by_ticker("AAPL", force_refresh=True)

    # Network timeout retries
    session_timeout = MagicMock(spec=requests.Session)
    session_timeout.headers = {}
    session_timeout.get.side_effect = requests.Timeout("timed out")
    client_timeout = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs analyst@finovalabs.ai",
        session=session_timeout,
        max_retries=1,
        sleep_fn=lambda _: None,
    )
    with pytest.raises(SecClientError, match="timed out"):
        client_timeout.lookup_company_by_ticker("AAPL", force_refresh=True)


def test_missing_ticker_and_missing_10k(tmp_path: Path) -> None:
    """Missing ticker or missing 10-K raises clear SecClientError."""
    settings = _build_settings(tmp_path)
    no_10k_submissions = {
        "cik": "0000320193",
        "name": "Example Corp",
        "tickers": ["EXMP"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-25-000001"],
                "filingDate": ["2025-01-10"],
                "reportDate": ["2024-12-31"],
                "form": ["8-K"],
                "primaryDocument": ["doc.htm"],
            },
            "files": [],
        },
    }
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = [
        _make_response(200, _sample_tickers_payload()),
        _make_response(200, no_10k_submissions),
    ]

    client = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs analyst@finovalabs.ai",
        session=session,
        sleep_fn=lambda _: None,
    )
    with pytest.raises(SecClientError, match="not found"):
        client.lookup_company_by_ticker("ZZZZ")

    with pytest.raises(SecClientError, match="No Form 10-K"):
        client.get_latest_10k("0000320193")
