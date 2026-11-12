"""Live SEC EDGAR verification tests retrieving real filing metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from finova_labs.database import fetch_filing_metadata, init_db
from finova_labs.exceptions import ConfigurationError
from finova_labs.filing_manager import retrieve_selected_companies
from finova_labs.sec_client import SecEdgarClient
from finova_labs.settings import get_settings, resolve_sec_user_agent


def test_live_sec_latest_10k_metadata(tmp_path: Path) -> None:
    """Retrieve real SEC filing metadata and Company Facts for AAPL using .env User-Agent."""
    settings = get_settings()
    try:
        user_agent = resolve_sec_user_agent(settings, require_real_email=True)
    except ConfigurationError as exc:
        pytest.skip(f"Live SEC check requires .env contact email: {exc}")

    db_file = tmp_path / "live_sec_test.db"
    init_db(db_file)

    client = SecEdgarClient(settings=settings, user_agent=user_agent)
    bundle = client.fetch_latest_10k_bundle("AAPL", persist=True, db_path=db_file)

    assert bundle.company.cik == "0000320193"
    assert bundle.company.ticker == "AAPL"
    assert bundle.latest_10k.form_type == "10-K"
    assert len(bundle.latest_10k.accession_number) >= 18
    assert len(bundle.latest_10k.filing_date) == 10
    assert bundle.latest_10k.fiscal_year is not None
    assert bundle.latest_10k.filing_url.startswith("https://www.sec.gov/Archives/edgar/data/")
    assert bundle.latest_10k.submissions_url.endswith("CIK0000320193.json")
    assert bundle.latest_10k.companyfacts_url.endswith("CIK0000320193.json")
    assert "us-gaap" in bundle.company_facts.facts

    stored = fetch_filing_metadata(cik="0000320193", form_type="10-K", db_path=db_file)
    assert len(stored) == 1
    assert stored[0]["accession_number"] == bundle.latest_10k.accession_number


def test_live_sec_all_five_supported_companies(tmp_path: Path) -> None:
    """Resolve real CIKs and retrieve latest 10-K metadata for AAPL, MSFT, GOOGL, AMZN, WMT."""
    settings = get_settings()
    try:
        user_agent = resolve_sec_user_agent(settings, require_real_email=True)
    except ConfigurationError as exc:
        pytest.skip(f"Live SEC check requires .env contact email: {exc}")

    db_file = tmp_path / "live_five_companies.db"
    init_db(db_file)

    client = SecEdgarClient(settings=settings, user_agent=user_agent)
    outcomes = retrieve_selected_companies(
        tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "WMT"],
        client=client,
        db_path=db_file,
    )

    assert len(outcomes) == 5
    assert all(o.retrieval_status == "RETRIEVED" for o in outcomes)
    assert all(o.cik and len(o.cik) == 10 for o in outcomes)
    assert all(o.filing_type == "10-K" for o in outcomes)
    assert all(o.filing_date and o.fiscal_year for o in outcomes)

    stored = fetch_filing_metadata(db_path=db_file)
    assert len(stored) == 5
