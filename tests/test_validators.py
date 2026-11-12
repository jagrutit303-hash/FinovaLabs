"""Comprehensive tests for FinovaLabs financial validation rules and escalation."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finova_labs.database import (
    fetch_audit_events,
    fetch_extracted_metrics,
    fetch_review_tasks,
    fetch_validation_results,
    init_db,
    save_extracted_metrics,
)
from finova_labs.extractor import CandidateFact, ExtractedMetricRecord, extract_metrics_for_filing
from finova_labs.filing_parser import parse_filing_html
from finova_labs.sec_client import FilingMetadata
from finova_labs.settings import ValidationSettings, get_settings
from finova_labs.validators import (
    PriorPeriodPoint,
    SegmentRevenueItem,
    run_financial_validations,
    validate_accounting_equation,
    validate_segment_revenue,
    validate_yoy_comparisons,
)


def _rec(
    metric_name: str,
    val: Decimal | None,
    *,
    concept: str | None = "Concept",
    unit: str = "USD",
    currency: str = "USD",
    scale_factor: Decimal = Decimal(1),
    period_start: str | None = None,
    period_end: str | None = "2024-09-28",
    fiscal_year: int | None = 2024,
    extraction_status: str = "EXTRACTED",
    accn: str = "0000320193-24-000123",
) -> ExtractedMetricRecord:
    return ExtractedMetricRecord(
        cik="0000320193",
        ticker="AAPL",
        accession_number=accn,
        form_type="10-K",
        metric_name=metric_name,
        xbrl_concept=concept,
        raw_value=str(val) if val is not None else None,
        normalized_value=val,
        reported_unit=unit,
        currency=currency,
        scale_factor=scale_factor,
        fiscal_period="FY",
        fiscal_year=fiscal_year,
        period_start=period_start,
        period_end=period_end,
        source_url="https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
        evidence_snippet=f"{metric_name} evidence snippet",
        evidence_location="Table #1",
        extraction_status=extraction_status,
        candidates=(
            [
                CandidateFact(
                    concept=concept or "Concept",
                    rank=0,
                    raw_value=str(val),
                    normalized_value=val,
                    reported_unit=unit,
                    currency=currency,
                    scale_factor=scale_factor,
                    period_start=period_start,
                    period_end=period_end,
                    source="xbrl+html",
                    evidence_snippet=f"{metric_name} evidence snippet",
                    evidence_location="Table #1",
                )
            ]
            if val is not None and extraction_status == "EXTRACTED"
            else []
        ),
    )


def test_default_validation_thresholds() -> None:
    """Default YoY anomaly threshold is 30% and accounting identity tolerance is documented."""
    val_settings = get_settings().validation
    assert val_settings.yoy_change_alert_threshold == pytest.approx(0.30)
    assert val_settings.accounting_identity_tolerance == pytest.approx(0.0005)
    assert val_settings.segment_reconciliation_tolerance == pytest.approx(0.02)


def test_accounting_equation_pass_rounding_fail_and_not_applicable() -> None:
    """Accounting equation handles exact match, display-scale rounding, material failure, and missing inputs."""
    # Exact match -> PASS
    exact = [
        _rec("Total Assets", Decimal("1000"), concept="Assets"),
        _rec("Total Liabilities", Decimal("600"), concept="Liabilities"),
        _rec("Shareholders' Equity", Decimal("400"), concept="StockholdersEquity"),
    ]
    res_exact = validate_accounting_equation(exact, settings=ValidationSettings())
    assert res_exact.status == "PASS"
    assert res_exact.escalate_to_review is False
    assert len(res_exact.input_metric_refs) == 3
    datetime.fromisoformat(res_exact.evaluated_at)

    # Display-unit rounding tolerance ($1M difference on $1M-scaled statements) -> PASS
    rounded = [
        _rec("Total Assets", Decimal("364980000000"), concept="Assets", scale_factor=Decimal("1000000")),
        _rec("Total Liabilities", Decimal("308030000000"), concept="Liabilities", scale_factor=Decimal("1000000")),
        _rec("Shareholders' Equity", Decimal("56951000000"), concept="StockholdersEquity", scale_factor=Decimal("1000000")),
    ]
    res_rounded = validate_accounting_equation(rounded, settings=ValidationSettings())
    assert res_rounded.status == "PASS"
    assert res_rounded.variance_abs == Decimal("1000000")

    # Material imbalance -> FAIL + escalate
    broken = [
        _rec("Total Assets", Decimal("1000"), concept="Assets"),
        _rec("Total Liabilities", Decimal("600"), concept="Liabilities"),
        _rec("Shareholders' Equity", Decimal("350"), concept="StockholdersEquity"),
    ]
    res_broken = validate_accounting_equation(broken, settings=ValidationSettings())
    assert res_broken.status == "FAIL"
    assert res_broken.escalate_to_review is True
    assert set(res_broken.affected_metrics) == {
        "Total Assets",
        "Total Liabilities",
        "Shareholders' Equity",
    }

    # Missing metric -> NOT_APPLICABLE (never PASS)
    incomplete = [
        _rec("Total Assets", Decimal("1000"), concept="Assets"),
        _rec("Total Liabilities", None, concept=None, extraction_status="MISSING"),
        _rec("Shareholders' Equity", Decimal("400"), concept="StockholdersEquity"),
    ]
    res_na = validate_accounting_equation(incomplete, settings=ValidationSettings())
    assert res_na.status == "NOT_APPLICABLE"
    assert res_na.escalate_to_review is False


def test_segment_revenue_pass_fail_and_unavailable_not_applicable() -> None:
    """Segment revenue check passes on reconciliation, fails on mismatch, and returns NOT_APPLICABLE when unavailable."""
    cons_rev = _rec(
        "Revenue",
        Decimal("391035000000"),
        concept="Revenues",
        period_start="2023-10-01",
        period_end="2024-09-28",
    )

    # Inline XBRL HTML with comparable operating segments on StatementBusinessSegmentsAxis
    seg_html = """
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
      <body>
        <ix:header><ix:resources>
          <xbrli:context id="c_americas">
            <xbrli:entity>
              <xbrli:segment><xbrldi:explicitMember dimension="srt:StatementBusinessSegmentsAxis">co:AmericasMember</xbrldi:explicitMember></xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:context id="c_europe">
            <xbrli:entity>
              <xbrli:segment><xbrldi:explicitMember dimension="srt:StatementBusinessSegmentsAxis">co:EuropeMember</xbrldi:explicitMember></xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:context id="c_prod">
            <xbrli:entity>
              <xbrli:segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">co:HardwareMember</xbrldi:explicitMember></xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
          </xbrli:context>
        </ix:resources></ix:header>
        <table>
          <tr><td>Americas</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c_americas" scale="6" unitRef="usd">200,000</ix:nonFraction></td></tr>
          <tr><td>Europe</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c_europe" scale="6" unitRef="usd">191,035</ix:nonFraction></td></tr>
          <tr><td>Hardware</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c_prod" scale="6" unitRef="usd">290,000</ix:nonFraction></td></tr>
        </table>
      </body>
    </html>
    """
    parsed = parse_filing_html(seg_html)
    res_pass = validate_segment_revenue(cons_rev, parsed_html=parsed, settings=ValidationSettings())
    assert res_pass.status == "PASS"
    assert res_pass.actual_value == Decimal("391035000000")
    assert res_pass.escalate_to_review is False

    # Segment mismatch exceeding 2% tolerance -> FAIL + escalate
    bad_segments = [
        SegmentRevenueItem(segment_name="Americas", value=Decimal("200000000000"), period_end="2024-09-28"),
        SegmentRevenueItem(segment_name="Europe", value=Decimal("100000000000"), period_end="2024-09-28"),
    ]
    res_fail = validate_segment_revenue(cons_rev, segment_items=bad_segments, settings=ValidationSettings())
    assert res_fail.status == "FAIL"
    assert res_fail.escalate_to_review is True
    assert res_fail.affected_metrics == ["Revenue"]

    # Segment info unavailable (no HTML) -> NOT_APPLICABLE, never PASS
    res_unavail = validate_segment_revenue(cons_rev, parsed_html=None, settings=ValidationSettings())
    assert res_unavail.status == "NOT_APPLICABLE"
    assert "not applicable" in res_unavail.explanation.lower()

    # Non-segment axis only (product axis without operating segments) -> NOT_APPLICABLE
    prod_only_html = """
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
      <body>
        <ix:header><ix:resources>
          <xbrli:context id="c_prod">
            <xbrli:entity>
              <xbrli:segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">co:HardwareMember</xbrldi:explicitMember></xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
          </xbrli:context>
        </ix:resources></ix:header>
        <table><tr><td>Hardware</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c_prod" scale="6" unitRef="usd">290,000</ix:nonFraction></td></tr></table>
      </body>
    </html>
    """
    res_prod_only = validate_segment_revenue(
        cons_rev,
        parsed_html=parse_filing_html(prod_only_html),
        settings=ValidationSettings(),
    )
    assert res_prod_only.status == "NOT_APPLICABLE"


def test_yoy_pass_warning_missing_fy_change_negative_restatement_and_noncomparable() -> None:
    """YoY validation covers <=30% PASS, >30% WARNING, missing period, FY change, negative values, restatements, and unit mismatch."""
    # 1. PASS (+10% <= 30%)
    rev_cur = _rec("Revenue", Decimal("110"), period_start="2023-10-01", period_end="2024-09-28")
    rev_prior = _rec("Revenue", Decimal("100"), period_start="2022-09-25", period_end="2023-09-30", fiscal_year=2023)
    res_pass = validate_yoy_comparisons([rev_cur], prior_records=[rev_prior], settings=ValidationSettings())[0]
    assert res_pass.status == "PASS"
    assert res_pass.variance_pct == pytest.approx(Decimal("0.10"))

    # 2. WARNING (>30% anomaly threshold) + configurable threshold test
    rev_spike = _rec("Revenue", Decimal("145"), period_start="2023-10-01", period_end="2024-09-28")
    res_warn = validate_yoy_comparisons([rev_spike], prior_records=[rev_prior], settings=ValidationSettings())[0]
    assert res_warn.status == "WARNING"
    assert res_warn.variance_pct == pytest.approx(Decimal("0.45"))

    res_custom_pass = validate_yoy_comparisons(
        [rev_spike],
        prior_records=[rev_prior],
        settings=ValidationSettings(yoy_change_alert_threshold=0.50),
    )[0]
    assert res_custom_pass.status == "PASS"

    # 3. Missing prior period -> NOT_APPLICABLE
    res_missing = validate_yoy_comparisons([rev_cur], settings=ValidationSettings())[0]
    assert res_missing.status == "NOT_APPLICABLE"

    # 4. Non-comparable unit mismatch -> NOT_APPLICABLE
    prior_wrong_unit = _rec("Revenue", Decimal("100"), unit="shares", period_start="2022-09-25", period_end="2023-09-30")
    res_unit = validate_yoy_comparisons([rev_cur], prior_records=[prior_wrong_unit], settings=ValidationSettings())[0]
    assert res_unit.status == "NOT_APPLICABLE"

    # 5. Fiscal-year change (short 270-day transition year / gap) -> WARNING
    fy_short_cur = _rec("Revenue", Decimal("80"), period_start="2024-01-01", period_end="2024-09-28")
    fy_full_prior = _rec("Revenue", Decimal("100"), period_start="2023-01-01", period_end="2023-12-31", fiscal_year=2023)
    res_fy = validate_yoy_comparisons([fy_short_cur], prior_records=[fy_full_prior], settings=ValidationSettings())[0]
    assert res_fy.status == "WARNING"
    assert "fiscal-year" in res_fy.explanation.lower()

    # 6. Negative values: (-100 -> -115 = -15% magnitude, stays <= 30% PASS using abs(prior))
    ni_cur_neg = _rec("Net Income", Decimal("-115"), period_start="2023-10-01", period_end="2024-09-28")
    ni_prior_neg = _rec("Net Income", Decimal("-100"), period_start="2022-09-25", period_end="2023-09-30", fiscal_year=2023)
    res_neg = validate_yoy_comparisons([ni_cur_neg], prior_records=[ni_prior_neg], settings=ValidationSettings())[0]
    assert res_neg.status == "PASS"
    assert res_neg.variance_pct == pytest.approx(Decimal("-0.15"))

    # Sign reversal (-100 -> +20) -> WARNING
    ni_flip = _rec("Net Income", Decimal("20"), period_start="2023-10-01", period_end="2024-09-28")
    res_flip = validate_yoy_comparisons([ni_flip], prior_records=[ni_prior_neg], settings=ValidationSettings())[0]
    assert res_flip.status == "WARNING"
    assert "sign reversal" in res_flip.explanation.lower()

    # Zero prior base -> WARNING (no ZeroDivisionError)
    res_zero = validate_yoy_comparisons(
        [ni_flip],
        prior_points={
            "Net Income": PriorPeriodPoint(
                metric_name="Net Income",
                value=Decimal("0"),
                period_start="2022-09-25",
                period_end="2023-09-30",
            )
        },
        settings=ValidationSettings(),
    )[0]
    assert res_zero.status == "WARNING"
    assert res_zero.variance_pct is None

    # 7. Restatement in SEC Company Facts -> uses latest restated figure & flags WARNING
    facts_restated = {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "val": 90,
                            "accn": "0000320193-23-000100",
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2023,
                            "filed": "2023-11-01",
                            "start": "2022-09-25",
                            "end": "2023-09-30",
                        },
                        {
                            "val": 100,
                            "accn": "0000320193-24-000123",
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2023,
                            "filed": "2024-11-01",
                            "start": "2022-09-25",
                            "end": "2023-09-30",
                        },
                    ]
                }
            }
        }
    }
    rev_cur_restate = _rec("Revenue", Decimal("110"), concept="Revenues", period_start="2023-10-01", period_end="2024-09-28")
    res_restate = validate_yoy_comparisons([rev_cur_restate], company_facts=facts_restated, settings=ValidationSettings())[0]
    assert res_restate.status == "WARNING"
    assert res_restate.expected_value == Decimal("100")
    assert "restatement" in res_restate.explanation.lower()


def test_failed_validation_persists_to_sqlite_and_escalates_to_human_review(tmp_path: Path) -> None:
    """Failed validations update metric validation_status='FAIL', review_status='REVIEW_REQUIRED', and open review_tasks."""
    db_path = tmp_path / "validation_escalate.db"
    accn = "0000320193-24-000123"
    filing = FilingMetadata(
        cik="0000320193",
        ticker="AAPL",
        company_name="Apple Inc.",
        accession_number=accn,
        form_type="10-K",
        filing_date="2024-11-01",
        reporting_period="2024-09-28",
        fiscal_year=2024,
        primary_document="aapl-20240928.htm",
        filing_url=f"https://www.sec.gov/Archives/edgar/data/320193/{accn.replace('-', '')}/aapl-20240928.htm",
        submissions_url="https://data.sec.gov/submissions/CIK0000320193.json",
        companyfacts_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
    )

    records = [
        _rec("Total Assets", Decimal("1000"), concept="Assets"),
        _rec("Total Liabilities", Decimal("600"), concept="Liabilities"),
        _rec("Shareholders' Equity", Decimal("300"), concept="StockholdersEquity"),  # off by 100 -> FAIL
        _rec("Revenue", Decimal("500"), concept="Revenues", period_start="2023-10-01"),
    ]
    init_db(db_path)
    save_extracted_metrics(
        records=[r.to_db_row() for r in records],
        cik=filing.cik,
        accession_number=accn,
        db_path=db_path,
    )

    validations = run_financial_validations(
        records,
        cik=filing.cik,
        ticker=filing.ticker,
        accession_number=accn,
        settings=ValidationSettings(),
        persist=True,
        db_path=db_path,
    )

    by_rule = {(v.rule_name, v.metric_name): v for v in validations}
    assert by_rule[("accounting_equation", "Accounting Equation (A = L + E)")].status == "FAIL"
    assert by_rule[("segment_revenue", "Segment Revenue Reconciliation")].status == "NOT_APPLICABLE"

    stored_vals = fetch_validation_results(accession_number=accn, db_path=db_path)
    assert len(stored_vals) == len(validations)
    for row in stored_vals:
        assert row["status"] in {"PASS", "FAIL", "WARNING", "NOT_APPLICABLE"}
        assert row["explanation"]
        assert len(json.loads(row["input_metric_refs_json"])) >= 1
        datetime.fromisoformat(row["evaluated_at"])

    stored_metrics = fetch_extracted_metrics(accession_number=accn, db_path=db_path)
    by_metric = {m["metric_name"]: m for m in stored_metrics}
    for bs_metric in ("Total Assets", "Total Liabilities", "Shareholders' Equity"):
        assert by_metric[bs_metric]["validation_status"] == "FAIL"
        assert by_metric[bs_metric]["review_status"] == "REVIEW_REQUIRED"

    tasks = fetch_review_tasks(status="OPEN", db_path=db_path)
    task_metrics = {t["metric_name"] for t in tasks}
    assert {"Total Assets", "Total Liabilities", "Shareholders' Equity"}.issubset(task_metrics)

    # Re-running validations remains idempotent on OPEN review_tasks
    run_financial_validations(
        records,
        cik=filing.cik,
        ticker=filing.ticker,
        accession_number=accn,
        settings=ValidationSettings(),
        persist=True,
        db_path=db_path,
    )
    assert len(fetch_review_tasks(status="OPEN", db_path=db_path)) == len(tasks)

    events = fetch_audit_events(db_path=db_path)
    event_types = {e["event_type"] for e in events}
    assert "VALIDATIONS_COMPLETED" in event_types
    assert "VALIDATION_FAILURES_ESCALATED" in event_types
