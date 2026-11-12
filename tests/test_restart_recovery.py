"""Tests for workflow restart recovery after closing the app and idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

import finova_labs.workflow as workflow_mod
from finova_labs.database import (
    fetch_audit_events,
    fetch_audit_run,
    fetch_extracted_metrics,
    fetch_filing_id,
    fetch_recoverable_workflows,
    fetch_review_tasks,
    fetch_runs,
    fetch_validation_results,
    init_db,
    save_filing_metadata,
)
from finova_labs.metric_mapping import get_metric_definition
from finova_labs.sec_client import FilingMetadata
from finova_labs.workflow import (
    _RUN_INPUT_CACHE,
    build_workflow_idempotency_key,
    get_workflow_checkpoint_state,
    resume_audit_workflow,
    start_audit_workflow,
    submit_review_decision,
)


def test_workflow_recovers_after_restart_without_repeating_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After closing the app (clearing memory), resuming from SqliteSaver never re-runs extraction/validation."""
    db_path = tmp_path / "restart_recovery.db"
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
    facts = {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "val": 1000000000,
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
                            "val": 600000000,
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
                            "val": 400000000,
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
    html = """
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
      <body>
        <ix:header><ix:resources>
          <xbrli:context id="ctx_inst"><xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period></xbrli:context>
        </ix:resources></ix:header>
        <table>
          <tr><td>Total assets</td><td><ix:nonFraction name="us-gaap:Assets" contextRef="ctx_inst" scale="6" unitRef="usd">1000</ix:nonFraction></td></tr>
          <tr><td>Total liabilities</td><td><ix:nonFraction name="us-gaap:Liabilities" contextRef="ctx_inst" scale="6" unitRef="usd">600</ix:nonFraction></td></tr>
        </table>
      </body>
    </html>
    """
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    paused_outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )
    assert paused_outcome.paused is True
    assert paused_outcome.status == "PAUSED_FOR_REVIEW"
    run_id = paused_outcome.run_id

    # Simulate application shutdown: wipe all in-memory workflow runtime inputs and forbid re-running
    # extraction or validation steps after restart.
    _RUN_INPUT_CACHE.clear()

    def _forbid_repeat(*args, **kwargs):
        raise AssertionError("Already-completed side effect was illegally re-executed after restart!")

    monkeypatch.setattr(workflow_mod, "extract_metrics_for_filing", _forbid_repeat)
    monkeypatch.setattr(workflow_mod, "run_financial_validations", _forbid_repeat)

    # Verify checkpoint survives restart
    restored = get_workflow_checkpoint_state(run_id, db_path=db_path)
    assert restored is not None
    assert restored["extraction_done"] is True
    assert restored["validation_done"] is True
    assert restored["paused_for_review"] is True

    # Persist human decision to SQLite first (auto_resume=False), then resume cleanly from SqliteSaver
    task = fetch_review_tasks(status="OPEN", run_id=run_id, db_path=db_path)[0]
    decision_res = submit_review_decision(
        task_id=task["task_id"],
        action="APPROVE",
        reviewer_note="Verified balance sheet total in 10-K filing.",
        reviewer="audit.partner",
        auto_resume=False,
        db_path=db_path,
    )
    assert decision_res["decision"]["status"] == "APPROVED"
    assert decision_res["workflow_outcome"] is None  # persisted in SQLite BEFORE resume

    resumed_outcome = resume_audit_workflow(run_id, db_path=db_path)
    assert resumed_outcome.status == "COMPLETED"
    assert resumed_outcome.paused is False
    assert resumed_outcome.finalized is True
    assert resumed_outcome.executed_nodes == [
        "extract_and_score",
        "validate_and_gate",
        "human_review",
        "finalize",
    ]

    # Calling resume again after completion must be strictly idempotent
    second_resume = resume_audit_workflow(run_id, db_path=db_path)
    assert second_resume.status == "COMPLETED"
    assert second_resume.finalized is True

    events = fetch_audit_events(run_id=run_id, db_path=db_path)
    event_counts = {}
    for ev in events:
        event_counts[ev["event_type"]] = event_counts.get(ev["event_type"], 0) + 1

    assert event_counts["METRICS_EXTRACTED"] == 1
    assert event_counts["VALIDATIONS_COMPLETED"] == 1
    assert event_counts["WORKFLOW_PAUSED_FOR_REVIEW"] == 1
    assert event_counts["HUMAN_REVIEW_DECISION"] == 1
    assert event_counts["WORKFLOW_RESUMED"] == 1
    assert event_counts["WORKFLOW_COMPLETED"] == 1

    runs = {r["run_id"]: r for r in fetch_runs(db_path=db_path)}
    assert runs[run_id]["status"] == "COMPLETED"


def _sample_filing_and_facts(accn: str = "0000320193-24-000123") -> tuple[FilingMetadata, dict, str]:
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
    facts = {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "val": 1000000000,
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
                            "val": 600000000,
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
                            "val": 400000000,
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
    html = """
    <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
      <body>
        <ix:header><ix:resources>
          <xbrli:context id="ctx_inst"><xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period></xbrli:context>
        </ix:resources></ix:header>
        <table>
          <tr><td>Total assets</td><td><ix:nonFraction name="us-gaap:Assets" contextRef="ctx_inst" scale="6" unitRef="usd">1000</ix:nonFraction></td></tr>
          <tr><td>Total liabilities</td><td><ix:nonFraction name="us-gaap:Liabilities" contextRef="ctx_inst" scale="6" unitRef="usd">600</ix:nonFraction></td></tr>
        </table>
      </body>
    </html>
    """
    return filing, facts, html


def _persist_filing(filing: FilingMetadata, db_path: Path) -> int:
    init_db(db_path)
    return save_filing_metadata(
        cik=filing.cik,
        ticker=filing.ticker,
        company_name=filing.company_name,
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        filing_date=filing.filing_date,
        reporting_period=filing.reporting_period,
        fiscal_year=filing.fiscal_year,
        retrieval_status="RETRIEVED",
        primary_document=filing.primary_document,
        filing_url=filing.filing_url,
        submissions_url=filing.submissions_url,
        companyfacts_url=filing.companyfacts_url,
        fetched_at="2026-11-12T00:00:00+00:00",
        db_path=db_path,
    )


def test_mid_workflow_crash_recovery_resumes_from_checkpoint_without_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crash mid-workflow after extract_and_score, close app, reopen, and resume the same run cleanly."""
    db_path = tmp_path / "crash_recovery.db"
    filing, facts, html = _sample_filing_and_facts("0000320193-24-000777")
    saved_filing_id = _persist_filing(filing, db_path)

    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    real_validate = workflow_mod.run_financial_validations

    def _crash_on_validate(*args, **kwargs):
        raise RuntimeError("Simulated mid-workflow interruption inside validate_and_gate")

    monkeypatch.setattr(workflow_mod, "run_financial_validations", _crash_on_validate)

    expected_key = build_workflow_idempotency_key(filing)
    with pytest.raises(RuntimeError, match="Simulated mid-workflow interruption"):
        start_audit_workflow(
            filing,
            company_facts=facts,
            html_text=html,
            metrics=metrics,  # type: ignore[arg-type]
            db_path=db_path,
        )

    recoverable = fetch_recoverable_workflows(db_path=db_path)
    assert len(recoverable) == 1
    run_id = recoverable[0]["run_id"]
    assert recoverable[0]["status"] == "INTERRUPTED"
    assert recoverable[0]["current_stage"] == "EXTRACTED_AND_SCORED"
    assert recoverable[0]["filing_id"] == saved_filing_id
    assert recoverable[0]["idempotency_key"] == expected_key
    # Shareholders' Equity lacks an HTML cross-check in the fixture, so 1 review task was already queued
    assert recoverable[0]["open_review_count"] == 1

    persisted_metrics_before = fetch_extracted_metrics(run_id=run_id, db_path=db_path)
    assert len(persisted_metrics_before) == 3

    # Simulate application close and restart: wipe in-memory cache and forbid re-running extraction
    _RUN_INPUT_CACHE.clear()
    monkeypatch.setattr(
        workflow_mod,
        "extract_metrics_for_filing",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Extraction must not re-run on crash recovery!")),
    )
    monkeypatch.setattr(workflow_mod, "run_financial_validations", real_validate)

    # Calling start_audit_workflow with the same filing after restart finds & resumes the interrupted run_id
    paused_after_resume = resume_audit_workflow(run_id, db_path=db_path)
    assert paused_after_resume.run_id == run_id
    assert paused_after_resume.status == "PAUSED_FOR_REVIEW"
    assert paused_after_resume.current_stage == "PAUSED_FOR_REVIEW"
    assert paused_after_resume.paused is True

    # Extracted metrics must NOT be duplicated
    assert len(fetch_extracted_metrics(run_id=run_id, db_path=db_path)) == 3
    assert len(fetch_validation_results(accession_number=filing.accession_number, db_path=db_path)) >= 1

    # Commit human decision before resuming
    open_tasks = fetch_review_tasks(status="OPEN", run_id=run_id, db_path=db_path)
    assert len(open_tasks) == 1
    decision_res = submit_review_decision(
        task_id=open_tasks[0]["task_id"],
        action="APPROVE",
        reviewer_note="Verified after restart recovery.",
        reviewer="senior.reviewer",
        auto_resume=False,
        db_path=db_path,
    )
    assert decision_res["decision"]["status"] == "APPROVED"

    final_outcome = resume_audit_workflow(run_id, db_path=db_path)
    assert final_outcome.run_id == run_id
    assert final_outcome.status == "COMPLETED"
    assert final_outcome.current_stage == "FINALIZED"
    assert final_outcome.finalized is True

    assert len(fetch_runs(db_path=db_path)) == 1
    assert fetch_filing_id(filing.cik, filing.accession_number, db_path=db_path) == saved_filing_id
    events = fetch_audit_events(run_id=run_id, db_path=db_path)
    counts: dict[str, int] = {}
    for ev in events:
        counts[ev["event_type"]] = counts.get(ev["event_type"], 0) + 1
    assert counts["METRICS_EXTRACTED"] == 1
    assert counts["VALIDATIONS_COMPLETED"] == 1
    assert counts["WORKFLOW_PAUSED_FOR_REVIEW"] == 1
    assert counts["HUMAN_REVIEW_DECISION"] == 1
    assert counts["WORKFLOW_COMPLETED"] == 1


def test_idempotency_keys_prevent_duplicate_filings_runs_metrics_and_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated start_audit_workflow and submit_review_decision calls must be idempotent without duplicates."""
    db_path = tmp_path / "idempotency.db"
    filing, facts, html = _sample_filing_and_facts("0000320193-24-000888")
    filing_id = _persist_filing(filing, db_path)
    metrics = (
        get_metric_definition("Total Assets"),
        get_metric_definition("Total Liabilities"),
        get_metric_definition("Shareholders' Equity"),
    )

    first = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )
    assert first.paused is True
    assert first.reused_existing_run is False

    # Re-invoking start_audit_workflow with the same filing must reuse the paused run without re-extracting
    monkeypatch.setattr(
        workflow_mod,
        "extract_metrics_for_filing",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Duplicate run should not re-extract!")),
    )
    second = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_path,
    )
    assert second.run_id == first.run_id
    assert second.reused_existing_run is True
    assert second.idempotency_key == first.idempotency_key
    assert len(fetch_runs(db_path=db_path)) == 1
    assert len(fetch_extracted_metrics(run_id=first.run_id, db_path=db_path)) == 3
    run_row = fetch_audit_run(first.run_id, db_path=db_path)
    assert run_row is not None
    assert run_row["filing_id"] == filing_id

    # Idempotent decision replay using same decision_key must not fail or duplicate audit events
    task = fetch_review_tasks(status="OPEN", run_id=first.run_id, db_path=db_path)[0]
    dkey = "decision-approve-equity-v1"
    dec1 = submit_review_decision(
        task_id=task["task_id"],
        action="APPROVE",
        reviewer_note="Approved once",
        reviewer="analyst.one",
        decision_key=dkey,
        auto_resume=False,
        db_path=db_path,
    )
    assert dec1["decision"]["idempotent_replay"] is False

    dec2 = submit_review_decision(
        task_id=task["task_id"],
        action="APPROVE",
        reviewer_note="Approved once",
        reviewer="analyst.one",
        decision_key=dkey,
        auto_resume=False,
        db_path=db_path,
    )
    assert dec2["decision"]["idempotent_replay"] is True

    decision_events = [
        ev for ev in fetch_audit_events(run_id=first.run_id, db_path=db_path)
        if ev["event_type"] == "HUMAN_REVIEW_DECISION"
    ]
    assert len(decision_events) == 1

    # Conflicting decision on already-resolved task must be rejected
    with pytest.raises(ValueError, match="already resolved"):
        submit_review_decision(
            task_id=task["task_id"],
            action="REJECT",
            reviewer_note="Conflicting rejection",
            reviewer="analyst.two",
            decision_key="different-key",
            auto_resume=False,
            db_path=db_path,
        )
