"""Tests for FinovaLabs explainable confidence scoring and review escalation."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from finova_labs.confidence import SCORING_METHOD_DOC, score_extracted_metric
from finova_labs.database import (
    fetch_extracted_metrics,
    fetch_review_tasks,
    init_db,
)
from finova_labs.extractor import (
    CandidateFact,
    ExtractedMetricRecord,
    extract_metrics_for_filing,
)
from finova_labs.metric_mapping import get_metric_definition
from finova_labs.sec_client import FilingMetadata
from finova_labs.settings import ConfidenceSettings, ConfidenceWeights, get_settings


def _sample_record(
    *,
    metric_name: str = "Total Assets",
    concept: str | None = "Assets",
    normalized_value: Decimal | None = Decimal("364980000000"),
    reported_unit: str = "USD",
    currency: str = "USD",
    scale_factor: Decimal = Decimal("1000000"),
    fiscal_period: str = "FY",
    fiscal_year: int | None = 2024,
    period_start: str | None = None,
    period_end: str | None = "2024-09-28",
    source: str = "xbrl+html",
    evidence_snippet: str = "Consolidated Balance Sheets — Total assets: $364,980 million",
    evidence_location: str = "Table #12 (Balance Sheet) | xbrl:us-gaap:Assets",
    source_url: str = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
    extraction_status: str = "EXTRACTED",
    candidates: list[CandidateFact] | None = None,
) -> ExtractedMetricRecord:
    if candidates is None and extraction_status == "EXTRACTED" and concept and normalized_value is not None:
        candidates = [
            CandidateFact(
                concept=concept,
                rank=0,
                raw_value="364,980",
                normalized_value=normalized_value,
                reported_unit=reported_unit,
                currency=currency,
                scale_factor=scale_factor,
                fiscal_period=fiscal_period,
                fiscal_year=fiscal_year,
                period_start=period_start,
                period_end=period_end,
                source=source,
                evidence_snippet=evidence_snippet,
                evidence_location=evidence_location,
            )
        ]

    return ExtractedMetricRecord(
        cik="0000320193",
        ticker="AAPL",
        accession_number="0000320193-24-000123",
        form_type="10-K",
        metric_name=metric_name,
        xbrl_concept=concept,
        raw_value="364,980" if normalized_value is not None else None,
        normalized_value=normalized_value,
        reported_unit=reported_unit,
        currency=currency,
        scale_factor=scale_factor,
        fiscal_period=fiscal_period,
        fiscal_year=fiscal_year,
        period_start=period_start,
        period_end=period_end,
        source_url=source_url,
        evidence_snippet=evidence_snippet,
        evidence_location=evidence_location,
        extraction_status=extraction_status,
        candidates=candidates or [],
    )


def test_default_config_weights_and_threshold() -> None:
    """Default confidence configuration uses 25/25/20/20/10 weights and 0.90 threshold."""
    settings = get_settings()
    conf = settings.confidence
    assert conf.auto_approve_threshold == pytest.approx(0.90)
    assert conf.scoring_version == "1.0.0"
    assert conf.weights.label_concept_match == pytest.approx(0.25)
    assert conf.weights.reporting_period_match == pytest.approx(0.25)
    assert conf.weights.unit_scale_correctness == pytest.approx(0.20)
    assert conf.weights.evidence_quality == pytest.approx(0.20)
    assert conf.weights.independent_path_agreement == pytest.approx(0.10)
    assert "Unavailable Factor Rule" in SCORING_METHOD_DOC


def test_invalid_weights_raise_validation_error() -> None:
    """Weights that do not sum to 1.0 are rejected at configuration time."""
    with pytest.raises(ValidationError):
        ConfidenceWeights(
            label_concept_match=0.30,
            reporting_period_match=0.30,
            unit_scale_correctness=0.20,
            evidence_quality=0.20,
            independent_path_agreement=0.20,
        )


def test_high_confidence_extracted_metric_auto_approved() -> None:
    """Verified XBRL+HTML metric on primary concept and aligned annual period scores 1.00 and auto-approves."""
    rec = _sample_record()
    assessment = score_extracted_metric(
        rec,
        filing_reporting_period="2024-09-28",
        html_checked=True,
        settings=ConfidenceSettings(),
    )

    assert assessment.score == pytest.approx(1.0)
    assert assessment.threshold == pytest.approx(0.90)
    assert assessment.scoring_version == "1.0.0"
    assert assessment.decision == "AUTO_APPROVED"
    assert assessment.escalated_to_review is False
    assert assessment.unavailable_factors == []
    assert assessment.available_weight == pytest.approx(1.0)
    assert all(f.available and f.status == "PASS" for f in assessment.factors)
    assert "Auto-approved" in assessment.reasons[-1]


def test_unavailable_independent_path_not_pretended_to_pass() -> None:
    """Single-source XBRL extraction marks independent_path_agreement unavailable with 0.00 contribution."""
    rec = _sample_record(
        source="xbrl",
        evidence_location="SEC CompanyFacts JSON (us-gaap:Assets)",
        evidence_snippet="us-gaap:Assets = 364980000000 USD (accn=0000320193-24-000123, period=instant..2024-09-28)",
    )
    assessment = score_extracted_metric(
        rec,
        filing_reporting_period="2024-09-28",
        html_checked=False,
        settings=ConfidenceSettings(),
    )

    by_factor = {f.factor: f for f in assessment.factors}
    indep = by_factor["independent_path_agreement"]
    assert indep.available is False
    assert indep.raw_score is None
    assert indep.contribution == 0.0
    assert indep.status == "UNAVAILABLE"
    assert "independent_path_agreement" in assessment.unavailable_factors
    assert assessment.available_weight == pytest.approx(0.90)
    # 0.25 + 0.25 + 0.20 + (0.20 * 0.85) + 0.00 = 0.87 < 0.90 -> escalated
    assert assessment.score == pytest.approx(0.87)
    assert assessment.decision == "REVIEW_REQUIRED"
    assert assessment.escalated_to_review is True


def test_configurable_threshold_changes_approval_decision() -> None:
    """Lowering threshold below score converts single-source metric into AUTO_APPROVED."""
    rec = _sample_record(
        source="xbrl",
        evidence_location="SEC CompanyFacts JSON (us-gaap:Assets)",
        evidence_snippet="us-gaap:Assets = 364980000000 USD",
    )
    custom_settings = ConfidenceSettings(auto_approve_threshold=0.85)
    assessment = score_extracted_metric(
        rec,
        filing_reporting_period="2024-09-28",
        html_checked=False,
        settings=custom_settings,
    )
    assert assessment.score == pytest.approx(0.87)
    assert assessment.threshold == pytest.approx(0.85)
    assert assessment.decision == "AUTO_APPROVED"
    assert assessment.escalated_to_review is False


def test_low_confidence_period_unit_and_sign_violations_escalated() -> None:
    """Quarterly duration, wrong unit, and negative positive-only metric produce low score and escalate."""
    rec = _sample_record(
        metric_name="Revenue",
        concept="Revenues",
        normalized_value=Decimal("-500000"),
        reported_unit="shares",
        currency="EUR",
        period_start="2024-07-01",
        period_end="2024-09-28",  # 89-day Q3 duration for an annual duration metric
        fiscal_period="Q3",
        source="xbrl",
        evidence_location="SEC CompanyFacts JSON",
        evidence_snippet="Quarterly revenue item",
    )
    assessment = score_extracted_metric(
        rec,
        filing_reporting_period="2024-09-28",
        html_checked=True,
        settings=ConfidenceSettings(),
    )

    by_factor = {f.factor: f for f in assessment.factors}
    assert by_factor["reporting_period_match"].raw_score == pytest.approx(0.15)
    assert by_factor["unit_scale_correctness"].raw_score == pytest.approx(0.0)
    assert assessment.score < 0.60
    assert assessment.decision == "REVIEW_REQUIRED"
    assert assessment.escalated_to_review is True


def test_missing_evidence_and_missing_metric_cases() -> None:
    """Missing snippet penalizes evidence_quality; MISSING metric handles unavailable checks explicitly."""
    stripped_evidence = _sample_record(
        evidence_snippet="",
        evidence_location="",
        source_url="",
    )
    stripped_assessment = score_extracted_metric(
        stripped_evidence,
        filing_reporting_period="2024-09-28",
        html_checked=True,
        settings=ConfidenceSettings(),
    )
    assert stripped_assessment.factors[3].factor == "evidence_quality"
    assert stripped_assessment.factors[3].raw_score == pytest.approx(0.0)
    assert stripped_assessment.score < 0.90
    assert stripped_assessment.decision == "REVIEW_REQUIRED"

    missing_rec = _sample_record(
        metric_name="Total Liabilities",
        concept=None,
        normalized_value=None,
        period_end="2024-09-28",
        evidence_snippet="No annual 10-K fact found in Company Facts or HTML for concepts Liabilities.",
        extraction_status="MISSING",
        candidates=[],
    )
    missing_assessment = score_extracted_metric(
        missing_rec,
        filing_reporting_period="2024-09-28",
        html_checked=True,
        settings=ConfidenceSettings(),
    )
    assert missing_assessment.score == pytest.approx(0.0)
    assert "unit_scale_correctness" in missing_assessment.unavailable_factors
    assert "independent_path_agreement" in missing_assessment.unavailable_factors
    assert missing_assessment.decision == "REVIEW_REQUIRED"
    assert missing_assessment.escalated_to_review is True


def test_ambiguous_metric_always_escalates() -> None:
    """Conflicting candidate values produce low confidence and escalate to review."""
    c1 = CandidateFact(
        concept="Assets",
        rank=0,
        raw_value="364,980",
        normalized_value=Decimal("364980000000"),
        reported_unit="USD",
        currency="USD",
        scale_factor=Decimal("1000000"),
        period_end="2024-09-28",
        source="xbrl",
        evidence_snippet="us-gaap:Assets = 364980000000",
        evidence_location="SEC CompanyFacts JSON",
    )
    c2 = CandidateFact(
        concept="Assets",
        rank=0,
        raw_value="352,583",
        normalized_value=Decimal("352583000000"),
        reported_unit="USD",
        currency="USD",
        scale_factor=Decimal("1000000"),
        period_end="2024-09-28",
        source="xbrl",
        evidence_snippet="us-gaap:Assets = 352583000000",
        evidence_location="SEC CompanyFacts JSON",
    )
    rec = _sample_record(
        normalized_value=None,
        extraction_status="AMBIGUOUS",
        candidates=[c1, c2],
        evidence_snippet="Ambiguous candidates detected (2 distinct values).",
    )
    assessment = score_extracted_metric(
        rec,
        filing_reporting_period="2024-09-28",
        html_checked=False,
        settings=ConfidenceSettings(),
    )
    assert assessment.score < 0.90
    assert assessment.decision == "REVIEW_REQUIRED"
    assert assessment.escalated_to_review is True


def test_sqlite_persistence_and_review_escalation_end_to_end(tmp_path: Path) -> None:
    """extract_metrics_for_filing persists scores/components/reasons and escalates <0.90 to review_tasks."""
    db_path = tmp_path / "confidence_test.db"
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
    company_facts = {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "val": 364980000000,
                            "accn": accn,
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2024,
                            "end": "2024-09-28",
                        }
                    ]
                }
            },
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "val": 391035000000,
                            "accn": accn,
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2024,
                            "start": "2023-10-01",
                            "end": "2024-09-28",
                        }
                    ]
                }
            },
        }
    }
    html_text = """
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
      <body>
        <ix:header><ix:resources>
          <xbrli:context id="ctx_instant">
            <xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period>
          </xbrli:context>
        </ix:resources></ix:header>
        <table>
          <tr><td>Total assets</td><td>$ <ix:nonFraction name="us-gaap:Assets" contextRef="ctx_instant" scale="6" unitRef="usd">364,980</ix:nonFraction></td></tr>
        </table>
      </body>
    </html>
    """

    assets_def = get_metric_definition("Total Assets")
    revenue_def = get_metric_definition("Revenue")
    liab_def = get_metric_definition("Total Liabilities")
    assert assets_def and revenue_def and liab_def

    records = extract_metrics_for_filing(
        filing=filing,
        company_facts=company_facts,
        html_text=html_text,
        metrics=(assets_def, revenue_def, liab_def),
        persist=True,
        db_path=db_path,
    )
    assert len(records) == 3

    by_name = {r.metric_name: r for r in records}
    # Total Assets has xbrl+html -> 1.00 -> AUTO_APPROVED
    assert by_name["Total Assets"].confidence_score == pytest.approx(1.0)
    assert by_name["Total Assets"].review_status == "AUTO_APPROVED"
    # Revenue only had XBRL (no HTML tag in html_text) -> 0.87 < 0.90 -> REVIEW_REQUIRED
    assert by_name["Revenue"].confidence_score == pytest.approx(0.87)
    assert by_name["Revenue"].review_status == "REVIEW_REQUIRED"
    # Total Liabilities is missing -> 0.00 -> REVIEW_REQUIRED
    assert by_name["Total Liabilities"].confidence_score == pytest.approx(0.0)
    assert by_name["Total Liabilities"].review_status == "REVIEW_REQUIRED"

    stored = fetch_extracted_metrics(accession_number=accn, db_path=db_path)
    assert len(stored) == 3
    stored_by_name = {row["metric_name"]: row for row in stored}
    rev_row = stored_by_name["Revenue"]
    assert rev_row["confidence_score"] == pytest.approx(0.87)
    assert rev_row["confidence_threshold"] == pytest.approx(0.90)
    assert rev_row["scoring_version"] == "1.0.0"
    assert json.loads(rev_row["confidence_components_json"])["unavailable_factors"] == ["independent_path_agreement"]
    assert len(json.loads(rev_row["confidence_reasons"])) >= 5

    tasks = fetch_review_tasks(status="OPEN", db_path=db_path)
    task_metrics = {t["metric_name"] for t in tasks}
    assert task_metrics == {"Revenue", "Total Liabilities"}
    assert "Total Assets" not in task_metrics

    # Re-running extraction for the same filing must not duplicate OPEN tasks
    extract_metrics_for_filing(
        filing=filing,
        company_facts=company_facts,
        html_text=html_text,
        metrics=(assets_def, revenue_def, liab_def),
        persist=True,
        db_path=db_path,
    )
    tasks_after = fetch_review_tasks(status="OPEN", db_path=db_path)
    assert len(tasks_after) == 2


def test_legacy_review_tasks_migration_preserves_rows(tmp_path: Path) -> None:
    """Existing SQLite DBs with run_id NOT NULL on review_tasks migrate cleanly without data loss."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE audit_runs (
            run_id TEXT PRIMARY KEY,
            cik TEXT NOT NULL,
            ticker TEXT,
            company_name TEXT,
            form_type TEXT NOT NULL DEFAULT '10-K',
            fiscal_year INTEGER,
            accession_number TEXT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            notes TEXT
        );
        CREATE TABLE extracted_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            xbrl_concept TEXT,
            raw_value TEXT,
            normalized_value REAL,
            unit TEXT DEFAULT 'USD',
            period_start TEXT,
            period_end TEXT,
            confidence_score REAL,
            validation_status TEXT NOT NULL DEFAULT 'PENDING',
            review_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
            source_evidence TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE review_tasks (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            metric_id INTEGER,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            reviewer_note TEXT,
            resolved_value REAL,
            resolved_by TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        INSERT INTO audit_runs (run_id, cik, ticker, company_name, status, started_at)
        VALUES ('run-1', '0000320193', 'AAPL', 'Apple Inc.', 'COMPLETED', '2026-01-01T00:00:00Z');
        INSERT INTO review_tasks (task_id, run_id, reason, status, created_at)
        VALUES ('legacy-task-1', 'run-1', 'Legacy reason', 'OPEN', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    tasks = fetch_review_tasks(db_path=db_path)
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "legacy-task-1"
