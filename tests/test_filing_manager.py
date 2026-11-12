"""Offline unit tests for FinovaLabs company selection and 10-K filing management."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import requests

from finova_labs.database import fetch_filing_metadata, init_db
from finova_labs.filing_manager import (
    SUPPORTED_COMPANIES,
    retrieve_selected_companies,
)
from finova_labs.sec_client import SecEdgarClient
from finova_labs.settings import Settings


def _resp(status_code: int, payload: Any) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.headers = {}
    mock.json.return_value = payload
    return mock


def _all_tickers_payload() -> dict[str, Any]:
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
        "2": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "3": {"cik_str": 1018724, "ticker": "AMZN", "title": "AMAZON COM INC"},
        "4": {"cik_str": 104169, "ticker": "WMT", "title": "Walmart Inc."},
    }


def _submissions_for(cik: str, name: str, ticker: str, acc: str, fdate: str, rdate: str) -> dict[str, Any]:
    return {
        "cik": cik,
        "name": name,
        "tickers": [ticker],
        "filings": {
            "recent": {
                "accessionNumber": [acc],
                "filingDate": [fdate],
                "reportDate": [rdate],
                "form": ["10-K"],
                "primaryDocument": [f"{ticker.lower()}-10k.htm"],
                "primaryDocDescription": ["10-K"],
            },
            "files": [],
        },
    }


def _facts_for(cik_int: int, name: str, acc: str, fy: int) -> dict[str, Any]:
    return {
        "cik": cik_int,
        "entityName": name,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {"USD": [{"val": 1000, "fy": fy, "form": "10-K", "accn": acc}]}
                }
            }
        },
    }


def test_supported_companies_include_all_five_without_hardcoded_ciks() -> None:
    """All 5 target companies exist and none hardcode a CIK number."""
    tickers = [c.ticker for c in SUPPORTED_COMPANIES]
    assert tickers == ["AAPL", "MSFT", "GOOGL", "AMZN", "WMT"]
    for company in SUPPORTED_COMPANIES:
        assert "cik" not in company.model_dump()


def test_retrieve_and_deduplicate_across_all_five_companies(tmp_path: Path) -> None:
    """Selecting all 5 companies resolves CIKs, saves metadata, and prevents duplicates."""
    settings = Settings(
        project_root=tmp_path,
        sec={
            "user_agent": "FinovaLabs test@finovalabs.ai",
            "cache_dir": str(tmp_path / "cache"),
            "request_timeout_seconds": 10,
            "max_requests_per_second": 10,
        },
    )
    db_file = tmp_path / "filings.db"
    init_db(db_file)

    url_map: dict[str, Any] = {
        "https://www.sec.gov/files/company_tickers.json": _all_tickers_payload(),
        "https://data.sec.gov/submissions/CIK0000320193.json": _submissions_for(
            "0000320193", "Apple Inc.", "AAPL", "0000320193-24-000123", "2024-11-01", "2024-09-28"
        ),
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json": _facts_for(
            320193, "Apple Inc.", "0000320193-24-000123", 2024
        ),
        "https://data.sec.gov/submissions/CIK0000789019.json": _submissions_for(
            "0000789019", "MICROSOFT CORP", "MSFT", "0000950170-24-087843", "2024-07-30", "2024-06-30"
        ),
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json": _facts_for(
            789019, "MICROSOFT CORP", "0000950170-24-087843", 2024
        ),
        "https://data.sec.gov/submissions/CIK0001652044.json": _submissions_for(
            "0001652044", "Alphabet Inc.", "GOOGL", "0001652044-25-000014", "2025-02-05", "2024-12-31"
        ),
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0001652044.json": _facts_for(
            1652044, "Alphabet Inc.", "0001652044-25-000014", 2024
        ),
        "https://data.sec.gov/submissions/CIK0001018724.json": _submissions_for(
            "0001018724", "AMAZON COM INC", "AMZN", "0001018724-25-000004", "2025-02-07", "2024-12-31"
        ),
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0001018724.json": _facts_for(
            1018724, "AMAZON COM INC", "0001018724-25-000004", 2024
        ),
        "https://data.sec.gov/submissions/CIK0000104169.json": _submissions_for(
            "0000104169", "Walmart Inc.", "WMT", "0000104169-24-000021", "2024-03-15", "2024-01-31"
        ),
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000104169.json": _facts_for(
            104169, "Walmart Inc.", "0000104169-24-000021", 2024
        ),
    }

    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = lambda url, **kwargs: _resp(200, url_map[url])

    client = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs test@finovalabs.ai",
        session=session,
        sleep_fn=lambda _: None,
    )

    progress_calls: list[tuple[int, int, str]] = []
    outcomes = retrieve_selected_companies(
        tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "WMT"],
        on_progress=lambda i, n, t: progress_calls.append((i, n, t)),
        client=client,
        db_path=db_file,
    )

    assert len(outcomes) == 5
    assert all(o.retrieval_status == "RETRIEVED" for o in outcomes)
    assert all(o.fiscal_year == 2024 for o in outcomes)
    assert len(progress_calls) == 5

    stored_first = fetch_filing_metadata(db_path=db_file)
    assert len(stored_first) == 5

    # Re-retrieving the exact same filings must not create duplicate rows in SQLite
    outcomes_again = retrieve_selected_companies(
        tickers=["AAPL", "WMT"],
        client=client,
        db_path=db_file,
    )
    assert all(o.retrieval_status == "RETRIEVED" for o in outcomes_again)
    stored_second = fetch_filing_metadata(db_path=db_file)
    assert len(stored_second) == 5


def test_failed_sec_request_never_marks_filing_retrieved(tmp_path: Path) -> None:
    """Failed SEC calls return FAILED and write zero RETRIEVED records to SQLite."""
    settings = Settings(
        project_root=tmp_path,
        sec={
            "user_agent": "FinovaLabs test@finovalabs.ai",
            "cache_dir": str(tmp_path / "cache"),
            "request_timeout_seconds": 10,
            "max_requests_per_second": 10,
        },
    )
    db_file = tmp_path / "fail_test.db"
    init_db(db_file)

    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.side_effect = requests.ConnectionError("Network unreachable")

    client = SecEdgarClient(
        settings=settings,
        user_agent="FinovaLabs test@finovalabs.ai",
        session=session,
        max_retries=0,
        sleep_fn=lambda _: None,
    )

    outcomes = retrieve_selected_companies(
        tickers=["AAPL", "MSFT"],
        client=client,
        db_path=db_file,
    )
    assert len(outcomes) == 2
    assert all(o.retrieval_status == "FAILED" for o in outcomes)
    assert all(o.error_message for o in outcomes)
    assert fetch_filing_metadata(db_path=db_file) == []

