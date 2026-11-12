"""Tests for FinovaLabs mandatory human-in-the-loop review workflow and LangGraph interrupts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from finova_labs.database import (
    fetch_audit_events,
    fetch_extracted_metrics,
    fetch_review_tasks,
    fetch_runs,
)
from finova_labs.exceptions import WorkflowError
from finova_labs.metric_mapping import get_metric_definition
from finova_labs.sec_client import FilingMetadata
from finova_labs.workflow import (
    get_workflow_checkpoint_state,
    resume_audit_workflow,
    start_audit_workflow,
    submit_review_decision,
)


def _sample_filing(accn: str = "0000320193-24-000123") -> FilingMetadata:
    return FilingMetadata(
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


def _balance_sheet_payload(
    *,
    accn: str = "0000320193-24-000123",
    assets_val: int = 1000000000,
    liab_val: int = 600000000,
    eq_val: int = 400000000,
    include_equity_html: bool = True,
) -> tuple[dict, str]:
    facts = {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "val": assets_val,
                            "accn": accn,
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2024,
                            "end": "2024-09-28",
                        }
                    ]
                }
            },
            "Liabilities": {
                "units": {
                    "USD": [
                        {
                            "val": liab_val,
                            "accn": accn,
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2024,
                            "end": "2024-09-28",
                        }
                    ]
                }
            },
            "StockholdersEquity": {
                "units": {
                    "USD": [
                        {
                            "val": eq_val,
                            "accn": accn,
                            "form": "10-K",
                            "fp": "FY",
                            "fy": 2024,
                            "end": "2024-09-28",
                        }
                    ]
                }
            },
        }
    }
    equity_row = (
        f"<tr><td>Total shareholders' equity</td>"
        f"<td><ix:nonFraction name='us-gaap:StockholdersEquity' contextRef='ctx_inst' scale='6' unitRef='usd'>{eq_val // 1_000_000}</ix:nonFraction></td></tr>"
        if include_equity_html
        else ""
    )
    html = f"""
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
      <body>
        <ix:header><ix:resources>
          <xbrli:context id="ctx_inst"><xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period></xbrli:context>
        </ix:resources></ix:header>
        <table>
          <tr><td>Total assets</td><td><ix:nonFraction name="us-gaap:Assets" contextRef="ctx_inst" scale="6" unitRef="usd">{assets_val // 1_000_000}</ix:nonFraction></td></tr>
          <tr><td>Total liabilities</td><td><ix:nonFraction name="us-gaap:Liabilities" contextRef="ctx_inst" scale="6" unitRef="usd">{liab_val // 1_000_000}</ix:nonFraction></td></tr>
          {equity_row}
        </table>
      </body>
    </html>
    """
    return facts, html


def test_auto_approves_only_when_confidence_and_validation_both_pass(tmp_path: Path) -> None:
    """Workflow finishes cleanly without pausing when confidence >= 0.90 and validations PASS."""
    db_path = tmp_path / "wf_auto.db"
    filing = _sample_filing()
    facts, html = _balance_sheet_payload()
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )

    assert outcome.paused is False
    assert outcome.status == "COMPLETED"
    assert outcome.open_task_count == 0
    assert set(outcome.auto_approved_metrics) == {
        "Total Assets",
        "Total Liabilities",
        "Shareholders' Equity",
    }
    assert outcome.escalated_metrics == []
    assert outcome.executed_nodes == ["extract_and_score", "validate_and_gate", "finalize"]

    stored = fetch_extracted_metrics(run_id=outcome.run_id, db_path=db_path)
    assert all(m["review_status"] == "AUTO_APPROVED" for m in stored)
    assert fetch_review_tasks(db_path=db_path) == []


def test_pauses_on_low_confidence_and_supports_approve_and_resume(tmp_path: Path) -> None:
    """Metric below 0.90 confidence pauses at LangGraph interrupt, displays full details, and resumes on APPROVE."""
    db_path = tmp_path / "wf_low_conf.db"
    filing = _sample_filing()
    # Omit HTML for StockholdersEquity so Equity scores 0.87 (<0.90) -> escalates
    facts, html = _balance_sheet_payload(include_equity_html=False)
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )

    assert outcome.paused is True
    assert outcome.status == "PAUSED_FOR_REVIEW"
    assert outcome.escalated_metrics == ["Shareholders' Equity"]
    assert outcome.open_task_count == 1
    assert set(outcome.auto_approved_metrics) == {"Total Assets", "Total Liabilities"}

    cp_state = get_workflow_checkpoint_state(outcome.run_id, db_path=db_path)
    assert cp_state is not None
    assert cp_state["paused_for_review"] is True

    # Verify OPEN task captures required reviewer dashboard fields
    open_tasks = fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_path)
    assert len(open_tasks) == 1
    task = open_tasks[0]
    assert task["metric_name"] == "Shareholders' Equity"
    assert task["ticker"] == "AAPL"
    assert task["normalized_decimal"] == "400000000"
    assert task["unit"] == "USD"
    assert task["fiscal_year"] == 2024
    assert task["confidence_score"] == pytest.approx(0.87)
    assert task["source_evidence"]
    assert task["accession_number"] == filing.accession_number
    assert "0.90" in task["reason"] or "90.0%" in task["reason"]

    # Attempting premature resume while OPEN fails safely
    with pytest.raises(WorkflowError):
        resume_audit_workflow(outcome.run_id, db_path=db_path)

    # Approve and auto-resume
    res = submit_review_decision(
        task_id=task["task_id"],
        action="APPROVE",
        reviewer="jane.analyst",
        db_path=db_path,
    )
    assert res["decision"]["status"] == "APPROVED"
    assert res["workflow_outcome"]["status"] == "COMPLETED"
    assert res["workflow_outcome"]["paused"] is False

    # Original extracted value stays intact
    stored = {m["metric_name"]: m for m in fetch_extracted_metrics(run_id=outcome.run_id, db_path=db_path)}
    eq = stored["Shareholders' Equity"]
    assert eq["normalized_decimal"] == "400000000"
    assert eq["review_status"] == "APPROVED"
    assert eq["reviewed_decimal"] == "400000000"


def test_pauses_on_validation_failure_even_when_confidence_is_100_percent(tmp_path: Path) -> None:
    """High-confidence (1.00) records STILL pause if a mandatory validation fails."""
    db_path = tmp_path / "wf_val_fail.db"
    filing = _sample_filing()
    # 1000 != 600 + 300 (accounting equation FAILS even though all 3 metrics have xbrl+html 1.00 confidence)
    facts, html = _balance_sheet_payload(assets_val=1000000000, liab_val=600000000, eq_val=300000000)
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )

    assert outcome.paused is True
    assert outcome.status == "PAUSED_FOR_REVIEW"
    assert outcome.auto_approved_metrics == []
    assert set(outcome.escalated_metrics) == {
        "Total Assets",
        "Total Liabilities",
        "Shareholders' Equity",
    }
    assert outcome.open_task_count == 3


def test_edit_correct_requires_explanation_and_preserves_original_value(tmp_path: Path) -> None:
    """EDIT/CORRECT enforces an explanation, updates reviewed value, preserves original permanently, and resumes."""
    db_path = tmp_path / "wf_edit.db"
    filing = _sample_filing()
    facts, html = _balance_sheet_payload(include_equity_html=False)
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )
    task = fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_path)[0]

    # Missing explanation must fail
    with pytest.raises(ValueError, match="explanation"):
        submit_review_decision(
            task_id=task["task_id"],
            action="EDIT/CORRECT",
            corrected_value="405000000",
            reviewer_note="   ",
            db_path=db_path,
        )
    # Task remains OPEN
    assert len(fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_path)) == 1

    # Valid correction succeeds and permanently preserves original extracted value
    res = submit_review_decision(
        task_id=task["task_id"],
        action="EDIT",
        corrected_value=Decimal("405000000"),
        reviewer_note="Adjusted per Footnote 7 balance sheet reclassification.",
        reviewer="senior.auditor",
        db_path=db_path,
    )
    assert res["decision"]["status"] == "CORRECTED"
    assert res["decision"]["original_decimal"] == "400000000"
    assert res["decision"]["resolved_decimal"] == "405000000"
    assert res["workflow_outcome"]["status"] == "COMPLETED"

    stored = {m["metric_name"]: m for m in fetch_extracted_metrics(run_id=outcome.run_id, db_path=db_path)}
    eq = stored["Shareholders' Equity"]
    assert eq["normalized_decimal"] == "400000000"
    assert eq["normalized_value"] == pytest.approx(400000000.0)
    assert eq["reviewed_decimal"] == "405000000"
    assert eq["review_status"] == "CORRECTED"
    assert "Footnote 7" in eq["reviewer_note"]


def test_reject_requires_explanation_preserves_original_and_completes_with_rejections(tmp_path: Path) -> None:
    """REJECT enforces explanation, preserves original extracted value, and marks run COMPLETED_WITH_REJECTIONS."""
    db_path = tmp_path / "wf_reject.db"
    filing = _sample_filing()
    facts, html = _balance_sheet_payload(include_equity_html=False)
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )
    task = fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_path)[0]

    with pytest.raises(ValueError, match="explanation"):
        submit_review_decision(
            task_id=task["task_id"],
            action="REJECT",
            reviewer_note="",
            db_path=db_path,
        )

    res = submit_review_decision(
        task_id=task["task_id"],
        action="REJECT",
        reviewer_note="Rejected: XBRL tag reflects subsidiary figure, not consolidated equity.",
        reviewer="lead.reviewer",
        db_path=db_path,
    )
    assert res["decision"]["status"] == "REJECTED"
    assert res["workflow_outcome"]["status"] == "COMPLETED_WITH_REJECTIONS"

    stored = {m["metric_name"]: m for m in fetch_extracted_metrics(run_id=outcome.run_id, db_path=db_path)}
    eq = stored["Shareholders' Equity"]
    assert eq["normalized_decimal"] == "400000000"
    assert eq["reviewed_value"] is None
    assert eq["review_status"] == "REJECTED"

    runs = {r["run_id"]: r for r in fetch_runs(db_path=db_path)}
    assert runs[outcome.run_id]["status"] == "COMPLETED_WITH_REJECTIONS"

    events = [e["event_type"] for e in fetch_audit_events(run_id=outcome.run_id, db_path=db_path)]
    assert "HUMAN_REVIEW_DECISION" in events
    assert "WORKFLOW_RESUMED" in events
    assert "WORKFLOW_COMPLETED" in events
