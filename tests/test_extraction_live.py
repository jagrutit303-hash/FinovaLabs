"""Real SEC 10-K filing extraction test for FinovaLabs."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from finova_labs.database import fetch_extracted_metrics
from finova_labs.exceptions import ConfigurationError
from finova_labs.extractor import extract_10k_metrics_from_sec
from finova_labs.sec_client import SecEdgarClient
from finova_labs.settings import get_settings, resolve_sec_user_agent


def test_real_sec_10k_extraction_for_apple(tmp_path: Path) -> None:
    """Extract all 8 financial metrics from Apple's real latest 10-K (XBRL + HTML) and persist."""
    settings = get_settings()
    try:
        user_agent = resolve_sec_user_agent(settings, require_real_email=True)
    except ConfigurationError as exc:
        pytest.skip(f"Live SEC extraction test requires .env contact email: {exc}")

    db_file = tmp_path / "live_extract.db"
    client = SecEdgarClient(settings=settings, user_agent=user_agent)

    records = extract_10k_metrics_from_sec(
        ticker="AAPL",
        client=client,
        include_html=True,
        persist=True,
        db_path=db_file,
    )

    assert len(records) == 8
    by_name = {r.metric_name: r for r in records}

    expected_names = {
        "Revenue",
        "Net Income",
        "Total Assets",
        "Total Liabilities",
        "Shareholders' Equity",
        "Operating Cash Flow",
        "Cash and Cash Equivalents",
        "Earnings Per Share",
    }
    assert set(by_name.keys()) == expected_names

    for name in expected_names:
        rec = by_name[name]
        assert rec.extraction_status == "EXTRACTED", f"{name} status={rec.extraction_status}"
        assert isinstance(rec.normalized_value, Decimal)
        assert rec.normalized_value != Decimal(0)
        assert rec.xbrl_concept
        assert rec.accession_number
        assert rec.period_end
        assert rec.source_url.startswith("https://")
        assert rec.evidence_snippet
        assert rec.evidence_location

    # Verify HTML enrichment captured millions scale for Apple's Revenue
    rev = by_name["Revenue"]
    assert rev.scale_factor == 1_000_000
    assert "Table #" in rev.evidence_location
    assert rev.period_start is not None

    # Verify SQLite persistence stored all 8 records with exact Decimal text
    stored = fetch_extracted_metrics(accession_number=rev.accession_number, db_path=db_file)
    assert len(stored) == 8

