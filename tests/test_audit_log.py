"""Tests for append-only tamper-evident audit trail, atomic transactions, filtering, and later corrections."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import finova_labs.audit as audit_mod
from finova_labs.audit import get_audit_chain_status, record_audit_event, verify_audit_chain
from finova_labs.database import (
    fetch_audit_events,
    fetch_extracted_metrics,
    fetch_review_tasks,
    get_connection,
    init_db,
    record_human_review_decision,
    save_filing_metadata,
)
from finova_labs.metric_mapping import get_metric_definition
from finova_labs.sec_client import FilingMetadata
from finova_labs.workflow import (
    start_audit_workflow,
    submit_review_decision,
    submit_subsequent_review_correction,
)


def test_empty_audit_chain_is_valid(tmp_path: Path) -> None:
    """An initialized empty audit_events table verifies cleanly."""
    db_file = tmp_path / "test_audit.db"
    init_db(db_file)

    is_valid, count, reason = verify_audit_chain(db_file)
    assert is_valid is True
    assert count == 0
    assert reason is None


def test_append_and_verify_hash_chain(tmp_path: Path) -> None:
    """Appended audit events link via SHA-256 and detect tampering."""
    db_file = tmp_path / "test_audit.db"
    init_db(db_file)

    id1 = record_audit_event("RUN_CREATED", actor="analyst", run_id="run-001", payload={"cik": "0000320193"}, db_path=db_file)
    id2 = record_audit_event("RUN_PAUSED", actor="system", run_id="run-001", payload={"reason": "low_confidence"}, db_path=db_file)

    assert id2 > id1
    is_valid, count, reason = verify_audit_chain(db_file)
    assert is_valid is True
    assert count == 2
    assert reason is None

    events = fetch_audit_events(run_id="run-001", db_path=db_file)
    assert len(events) == 2

    # Simulate database tampering and confirm verification catches it.
    with get_connection(db_file) as conn:
        conn.execute("UPDATE audit_events SET payload_json = '{\"tampered\":true}' WHERE event_id = ?", (id1,))

    is_valid_after, _, reason_after = verify_audit_chain(db_file)
    assert is_valid_after is False
    assert reason_after is not None and f"event_id={id1}" in reason_after


def _seed_workflow_for_audit_tests(db_file: Path):
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
        filing_url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        submissions_url="https://data.sec.gov/submissions/CIK0000320193.json",
        companyfacts_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
    )
    save_filing_metadata(
        cik=filing.cik,
        ticker=filing.ticker,
        company_name=filing.company_name,
        accession_number=accn,
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
        db_path=db_file,
    )
    facts = {
        "us-gaap": {
            "Assets": {"units": {"USD": [{"val": 1000000000, "accn": accn, "form": "10-K", "fp": "FY", "fy": 2024, "end": "2024-09-28"}]}},
            "Liabilities": {"units": {"USD": [{"val": 600000000, "accn": accn, "form": "10-K", "fp": "FY", "fy": 2024, "end": "2024-09-28"}]}},
            "StockholdersEquity": {"units": {"USD": [{"val": 400000000, "accn": accn, "form": "10-K", "fp": "FY", "fy": 2024, "end": "2024-09-28"}]}},
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
    outcome = start_audit_workflow(
        filing,
        company_facts=facts,
        html_text=html,
        metrics=metrics,  # type: ignore[arg-type]
        db_path=db_file,
    )
    return filing, outcome


def test_decisions_store_full_fields_and_commit_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workflow and human decisions store complete metadata and roll back atomically on audit error."""
    db_file = tmp_path / "atomic_audit.db"
    init_db(db_file)
    filing, outcome = _seed_workflow_for_audit_tests(db_file)
    assert outcome.paused is True

    # Verify workflow AUTO_APPROVED and ESCALATED gating decisions were recorded atomically
    all_events = list(reversed(fetch_audit_events(run_id=outcome.run_id, db_path=db_file, limit=100)))
    seq_ids = [ev["seq_id"] for ev in all_events]
    assert seq_ids == list(range(1, len(all_events) + 1))

    gate_decisions = [ev for ev in all_events if ev["event_type"] == "WORKFLOW_DECISION"]
    assert {g["metric_name"]: g["decision"] for g in gate_decisions} == {
        "Total Assets": "AUTO_APPROVED",
        "Total Liabilities": "AUTO_APPROVED",
        "Shareholders' Equity": "ESCALATED",
    }
    for g in gate_decisions:
        assert g["cik"] == filing.cik
        assert g["ticker"] == "AAPL"
        assert g["company_name"] == "Apple Inc."
        assert g["accession_number"] == filing.accession_number
        assert g["run_id"] == outcome.run_id
        assert g["original_value"] is not None
        assert g["corrected_value"] is None
        assert g["explanation"]
        assert g["created_at"].endswith("+00:00")

    # Simulate failure when writing audit record during human review decision -> decision must roll back!
    open_task = fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_file)[0]
    real_insert = audit_mod._insert_audit_row

    def _boom_audit(*args, **kwargs):
        raise RuntimeError("Simulated audit sink failure")

    monkeypatch.setattr(audit_mod, "_insert_audit_row", _boom_audit)
    with pytest.raises(RuntimeError, match="Simulated audit sink failure"):
        submit_review_decision(
            task_id=open_task["task_id"],
            action="EDIT",
            corrected_value="405000000",
            reviewer_note="Should roll back completely",
            reviewer="analyst.rollback",
            session_id="sess-rollback",
            db_path=db_file,
        )

    # Confirm neither review_tasks nor extracted_metrics nor audit_events changed on rollback
    monkeypatch.setattr(audit_mod, "_insert_audit_row", real_insert)
    still_open = fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_file)
    assert len(still_open) == 1
    assert still_open[0]["task_id"] == open_task["task_id"]
    metrics_after_fail = {
        m["metric_name"]: m for m in fetch_extracted_metrics(run_id=outcome.run_id, db_path=db_file)
    }
    assert metrics_after_fail["Shareholders' Equity"]["review_status"] == "REVIEW_REQUIRED"
    assert metrics_after_fail["Shareholders' Equity"]["reviewed_decimal"] is None
    assert len(fetch_audit_events(run_id=outcome.run_id, db_path=db_file, limit=100)) == len(all_events)

    # Confirm honest tamper-evident model notice
    status = get_audit_chain_status(db_file)
    assert status["is_valid"] is True
    assert status["tamper_model"] == "tamper-evident"
    assert "not absolutely tamper-proof" in status["tamper_notice"].lower()


def test_previous_audit_records_remain_unchanged_after_later_corrections(tmp_path: Path) -> None:
    """Later corrections append new hash-chained records while earlier audit records stay byte-identical."""
    db_file = tmp_path / "append_only_history.db"
    init_db(db_file)
    filing, outcome = _seed_workflow_for_audit_tests(db_file)
    open_task = fetch_review_tasks(status="OPEN", run_id=outcome.run_id, db_path=db_file)[0]

    # Step 1: Initial human correction
    res1 = submit_review_decision(
        task_id=open_task["task_id"],
        action="EDIT",
        corrected_value=Decimal("405000000"),
        reviewer_note="Initial adjustment per Balance Sheet note.",
        reviewer="jane.analyst",
        session_id="sess-100",
        db_path=db_file,
    )
    assert res1["decision"]["status"] == "CORRECTED"
    assert res1["workflow_outcome"]["status"] == "COMPLETED"

    snapshot_after_first = list(
        reversed(fetch_audit_events(run_id=outcome.run_id, db_path=db_file, limit=200))
    )
    tasks_after_first = fetch_review_tasks(run_id=outcome.run_id, db_path=db_file)
    first_human_ev = next(ev for ev in snapshot_after_first if ev["event_type"] == "HUMAN_REVIEW_DECISION")
    assert first_human_ev["original_value"] == "400000000"
    assert first_human_ev["corrected_value"] == "405000000"
    assert first_human_ev["decision"] == "CORRECTED"
    assert first_human_ev["reviewer_id"] == "jane.analyst"
    assert first_human_ev["session_id"] == "sess-100"
    assert first_human_ev["explanation"] == "Initial adjustment per Balance Sheet note."
    assert first_human_ev["ticker"] == "AAPL"
    assert first_human_ev["accession_number"] == filing.accession_number
    assert first_human_ev["metric_name"] == "Shareholders' Equity"

    # Step 2: Later correction via submit_subsequent_review_correction
    res2 = submit_subsequent_review_correction(
        metric_id=open_task["metric_id"],
        action="EDIT",
        corrected_value=Decimal("408000000"),
        reviewer_note="Subsequent audit partner adjustment for share repurchase reclassification.",
        reviewer="audit.partner",
        session_id="sess-200",
        db_path=db_file,
    )
    assert res2["decision"]["is_subsequent_correction"] is True

    # Step 3: Another later decision via allow_amendment=True on the task
    res3 = submit_review_decision(
        task_id=open_task["task_id"],
        action="REJECT",
        reviewer_note="Superseded pending formal restatement review.",
        reviewer="chief.auditor",
        session_id="sess-300",
        allow_amendment=True,
        auto_resume=False,
        db_path=db_file,
    )
    assert res3["decision"]["status"] == "REJECTED"

    all_after = list(
        reversed(fetch_audit_events(run_id=outcome.run_id, db_path=db_file, limit=200))
    )
    assert len(all_after) == len(snapshot_after_first) + 2

    # Every single earlier audit record must remain 100% identical after later corrections
    assert all_after[: len(snapshot_after_first)] == snapshot_after_first
    assert [ev["seq_id"] for ev in all_after] == list(range(1, len(all_after) + 1))

    # Earlier review_task row also remained untouched; new amendment tasks were appended
    tasks_after = fetch_review_tasks(run_id=outcome.run_id, db_path=db_file)
    assert len(tasks_after) == len(tasks_after_first) + 2
    orig_task_after = next(t for t in tasks_after if t["task_id"] == open_task["task_id"])
    assert orig_task_after["status"] == "CORRECTED"
    assert orig_task_after["resolved_decimal"] == "405000000"

    # Verify new appended audit events store original permanent value alongside new decision/value
    human_events = [ev for ev in all_after if ev["event_type"] == "HUMAN_REVIEW_DECISION"]
    assert len(human_events) == 3
    assert [ev["corrected_value"] for ev in human_events] == ["405000000", "408000000", None]
    assert [ev["decision"] for ev in human_events] == ["CORRECTED", "CORRECTED", "REJECTED"]
    assert all(ev["original_value"] == "400000000" for ev in human_events)

    # Original extracted_metrics.normalized_decimal remains untouched forever
    stored_eq = next(
        m for m in fetch_extracted_metrics(run_id=outcome.run_id, db_path=db_file)
        if m["metric_name"] == "Shareholders' Equity"
    )
    assert stored_eq["normalized_decimal"] == "400000000"
    assert stored_eq["review_status"] == "REJECTED"

    # Chain integrity intact cleanly; editing any structured column breaks verification
    is_valid, count, reason = verify_audit_chain(db_file)
    assert is_valid is True
    assert count == len(all_after)
    assert reason is None

    tamper_id = first_human_ev["event_id"]
    with get_connection(db_file) as conn:
        conn.execute(
            "UPDATE audit_events SET corrected_value = '999999999' WHERE event_id = ?",
            (tamper_id,),
        )
    valid_tampered, _, reason_tampered = verify_audit_chain(db_file)
    assert valid_tampered is False
    assert reason_tampered is not None and f"event_id={tamper_id}" in reason_tampered


def test_audit_trail_filters_by_company_date_decision_and_metric(tmp_path: Path) -> None:
    """SQLite audit trail queries filter cleanly by company, UTC date, decision, and metric."""
    db_file = tmp_path / "filter_audit.db"
    init_db(db_file)

    record_audit_event(
        "HUMAN_REVIEW_DECISION",
        actor="analyst.a",
        run_id="run-aapl",
        cik="0000320193",
        ticker="AAPL",
        company_name="Apple Inc.",
        accession_number="0000320193-24-000123",
        metric_name="Revenue",
        decision="APPROVED",
        original_value="391035000000",
        explanation="Matched consolidated net sales.",
        created_at="2026-11-10T10:00:00+00:00",
        db_path=db_file,
    )
    record_audit_event(
        "HUMAN_REVIEW_DECISION",
        actor="analyst.b",
        run_id="run-aapl",
        cik="0000320193",
        ticker="AAPL",
        company_name="Apple Inc.",
        accession_number="0000320193-24-000123",
        metric_name="Net Income",
        decision="CORRECTED",
        original_value="93000000000",
        corrected_value="93736000000",
        explanation="Adjusted Net Income.",
        created_at="2026-11-11T15:30:00+00:00",
        db_path=db_file,
    )
    record_audit_event(
        "HUMAN_REVIEW_DECISION",
        actor="analyst.c",
        run_id="run-msft",
        cik="0000789019",
        ticker="MSFT",
        company_name="Microsoft Corporation",
        accession_number="0000789019-24-000456",
        metric_name="Net Income",
        decision="REJECTED",
        original_value="88136000000",
        explanation="Segmented income picked instead of consolidated.",
        created_at="2026-11-12T08:45:00+00:00",
        db_path=db_file,
    )

    assert len(fetch_audit_events(company="AAPL", db_path=db_file)) == 2
    assert len(fetch_audit_events(company="MSFT", db_path=db_file)) == 1
    assert len(fetch_audit_events(date="2026-11-11", db_path=db_file)) == 1
    assert len(fetch_audit_events(date_from="2026-11-11", date_to="2026-11-12", db_path=db_file)) == 2
    assert len(fetch_audit_events(decision="EDIT", db_path=db_file)) == 1
    assert len(fetch_audit_events(decision="REJECTED", db_path=db_file)) == 1
    assert len(fetch_audit_events(metric_name="Net Income", db_path=db_file)) == 2

    combined = fetch_audit_events(
        company="AAPL",
        date="2026-11-11",
        decision="CORRECTED",
        metric_name="Net Income",
        db_path=db_file,
    )
    assert len(combined) == 1
    assert combined[0]["corrected_value"] == "93736000000"
    assert verify_audit_chain(db_file) == (True, 3, None)
