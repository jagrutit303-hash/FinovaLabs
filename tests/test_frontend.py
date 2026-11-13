"""Automated Streamlit UI tests for all five FinovaLabs navigation screens (legacy - replaced with React)."""

from __future__ import annotations

import pytest

pytest.skip("Streamlit UI replaced with pure React frontend", allow_module_level=True)

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finova_labs.audit import record_audit_event
from finova_labs.database import (
    create_audit_run,
    fetch_review_tasks,
    init_db,
    record_human_review_decision,
    save_extracted_metrics,
    save_filing_metadata,
    save_validation_results,
    sync_review_tasks_for_filing,
)
from finova_labs.evaluation import evaluate_run_against_company_facts
from finova_labs.settings import Settings, load_typed_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_test_settings(tmp_path: Path) -> Settings:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
app:
  name: "FinovaLabs"
  tagline: "AI-Powered Financial Filing Auditor"
  db_path: "{(tmp_path / 'ui_test.db').as_posix()}"
  reports_dir: "{(tmp_path / 'reports').as_posix()}"
logging:
  level: "INFO"
  log_dir: "{(tmp_path / 'logs').as_posix()}"
  file_name: "finova_ui_test.log"
""",
        encoding="utf-8",
    )
    return load_typed_settings(cfg)


def _patch_ui_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Settings, Path]:
    settings = _make_test_settings(tmp_path)
    db_file = settings.db_file
    init_db(db_file)

    import finova_labs.database as db_mod
    import finova_labs.settings as settings_mod
    import finova_labs.views as views_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(views_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(db_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(db_mod, "resolve_db_path", lambda db_path=None: Path(db_path) if db_path else db_file)
    return settings, db_file


def _seed_sample_data(db_file: Path) -> str:
    accn = "0000320193-24-000123"
    run_id = "run-ui-001"
    save_filing_metadata(
        cik="0000320193",
        ticker="AAPL",
        company_name="Apple Inc.",
        accession_number=accn,
        form_type="10-K",
        filing_date="2024-11-01",
        reporting_period="2024-09-28",
        fiscal_year=2024,
        retrieval_status="RETRIEVED",
        primary_document="aapl-20240928.htm",
        filing_url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        submissions_url="https://data.sec.gov/submissions/CIK0000320193.json",
        companyfacts_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        fetched_at="2026-11-12T00:00:00+00:00",
        db_path=db_file,
    )
    create_audit_run(
        run_id=run_id,
        cik="0000320193",
        accession_number=accn,
        company_name="Apple Inc.",
        ticker="AAPL",
        form_type="10-K",
        fiscal_year=2024,
        status="PAUSED_FOR_REVIEW",
        current_stage="PAUSED_FOR_REVIEW",
        overall_confidence=0.875,
        db_path=db_file,
    )
    save_extracted_metrics(
        [
            {
                "run_id": run_id,
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": accn,
                "form_type": "10-K",
                "metric_name": "Revenue",
                "xbrl_concept": "Revenues",
                "raw_value": "391,035",
                "normalized_value": 391035000000.0,
                "normalized_decimal": "391035000000",
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1000000,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": "2023-10-01",
                "period_end": "2024-09-28",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "source_evidence": "Total net sales $391,035 million",
                "evidence_location": "HTML Table 1 Row 1",
                "extraction_status": "EXTRACTED",
                "confidence_score": 0.98,
                "confidence_threshold": 0.90,
                "scoring_version": "1.0.0",
                "validation_status": "PASS",
                "review_status": "AUTO_APPROVED",
                "created_at": "2026-11-12T00:00:00+00:00",
            },
            {
                "run_id": run_id,
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": accn,
                "form_type": "10-K",
                "metric_name": "Net Income",
                "xbrl_concept": "NetIncomeLoss",
                "raw_value": "93,000",
                "normalized_value": 93000000000.0,
                "normalized_decimal": "93000000000",
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1000000,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": "2023-10-01",
                "period_end": "2024-09-28",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "source_evidence": "Net income $93,736 million",
                "evidence_location": "CompanyFacts JSON",
                "extraction_status": "EXTRACTED",
                "confidence_score": 0.77,
                "confidence_threshold": 0.90,
                "scoring_version": "1.0.0",
                "validation_status": "PASS",
                "review_status": "REVIEW_REQUIRED",
                "created_at": "2026-11-12T00:00:00+00:00",
            },
            {
                "run_id": run_id,
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": accn,
                "form_type": "10-K",
                "metric_name": "Total Assets",
                "xbrl_concept": "Assets",
                "raw_value": "364,980",
                "normalized_value": 364980000000.0,
                "normalized_decimal": "364980000000",
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1000000,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": None,
                "period_end": "2024-09-28",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "source_evidence": "Total assets $364,980 million",
                "evidence_location": "HTML Balance Sheet",
                "extraction_status": "EXTRACTED",
                "confidence_score": 0.95,
                "confidence_threshold": 0.90,
                "scoring_version": "1.0.0",
                "validation_status": "PASS",
                "review_status": "REVIEW_REQUIRED",
                "created_at": "2026-11-12T00:00:00+00:00",
            },
        ],
        cik="0000320193",
        accession_number=accn,
        db_path=db_file,
    )
    save_validation_results(
        [
            {
                "validation_id": "val-ui-1",
                "run_id": run_id,
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": accn,
                "rule_name": "ACCOUNTING_EQUATION",
                "metric_name": "Balance Sheet Identity",
                "status": "PASS",
                "explanation": "Assets balance Liabilities + Equity within tolerance.",
                "input_metric_refs_json": '{"Assets": "364980000000"}',
                "expected_value": "364980000000",
                "actual_value": "364980000000",
                "variance_abs": "0",
                "variance_pct": "0",
                "tolerance_used": "0.0005",
                "escalated": 0,
                "evaluated_at": "2026-11-12T00:00:00+00:00",
            }
        ],
        cik="0000320193",
        accession_number=accn,
        db_path=db_file,
    )
    sync_review_tasks_for_filing(
        tasks=[
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "metric_name": "Net Income",
                "reason": "Confidence 77.0% < threshold 90.0%",
            },
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "metric_name": "Total Assets",
                "reason": "Manual verification test task",
            },
        ],
        cik="0000320193",
        accession_number=accn,
        db_path=db_file,
    )
    tasks = fetch_review_tasks(run_id=run_id, db_path=db_file)
    assets_task = next(t for t in tasks if t["metric_name"] == "Total Assets")
    record_human_review_decision(
        task_id=assets_task["task_id"],
        action="EDIT",
        corrected_value="364980000000",
        reviewer_note="Confirmed Total Assets against 10-K Consolidated Balance Sheet.",
        reviewer="audit.lead",
        db_path=db_file,
    )
    facts_payload = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
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
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "val": 93736000000,
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
            }
        },
    }
    evaluate_run_against_company_facts(run_id, company_facts=facts_payload, persist=True, db_path=db_file)
    record_audit_event(
        event_type="WORKFLOW_STARTED",
        actor="workflow",
        run_id=run_id,
        payload={"cik": "0000320193", "ticker": "AAPL"},
        db_path=db_file,
    )
    return run_id


def _run_view(fn) -> AppTest:
    at = AppTest.from_function(fn)
    at.run(timeout=20)
    assert not at.exception, f"Streamlit UI exception: {at.exception}"
    return at


def test_entrypoints_render_without_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify app.py and all standalone multipage scripts boot with zero exceptions."""
    _patch_ui_db(monkeypatch, tmp_path)
    targets = [
        PROJECT_ROOT / "app.py",
        PROJECT_ROOT / "pages" / "1_Run_Overview.py",
        PROJECT_ROOT / "pages" / "2_Metrics_Evidence.py",
        PROJECT_ROOT / "pages" / "3_Human_Review.py",
        PROJECT_ROOT / "pages" / "4_Accuracy_Audit.py",
    ]
    for script in targets:
        at = AppTest.from_file(str(script))
        at.run(timeout=20)
        assert not at.exception, f"{script.name} raised UI exception: {at.exception}"


def test_all_five_views_render_clean_empty_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify every FinovaLabs navigation view handles empty SQLite tables gracefully."""
    _patch_ui_db(monkeypatch, tmp_path)

    def _overview():
        from finova_labs.views import render_overview_page
        render_overview_page()

    def _filing():
        from finova_labs.views import render_filing_analysis_page
        render_filing_analysis_page()

    def _review():
        from finova_labs.views import render_human_review_page
        render_human_review_page()

    def _accuracy():
        from finova_labs.views import render_accuracy_report_page
        render_accuracy_report_page()

    def _audit():
        from finova_labs.views import render_audit_trail_page
        render_audit_trail_page()

    for view_fn in (_overview, _filing, _review, _accuracy, _audit):
        _run_view(view_fn)


def test_all_five_views_render_real_sqlite_data_and_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify populated data, Plotly charts, filters, and working Human Review / Audit actions."""
    _, db_file = _patch_ui_db(monkeypatch, tmp_path)
    _seed_sample_data(db_file)

    def _overview():
        from finova_labs.views import render_overview_page
        render_overview_page()

    def _filing():
        from finova_labs.views import render_filing_analysis_page
        render_filing_analysis_page()

    def _review():
        from finova_labs.views import render_human_review_page
        render_human_review_page()

    def _accuracy():
        from finova_labs.views import render_accuracy_report_page
        render_accuracy_report_page()

    def _audit():
        from finova_labs.views import render_audit_trail_page
        render_audit_trail_page()

    # 1. Overview with real metrics + DB Health button + Plotly charts
    at_ov = _run_view(_overview)
    db_btn = next(b for b in at_ov.button if b.label == "Verify DB Health")
    db_btn.click().run(timeout=20)
    assert not at_ov.exception
    assert any("SQLite OK" in s.value for s in at_ov.success)

    # 2. Filing Analysis: test 'Select all 5 companies' syncs multiselect cleanly
    at_fa = _run_view(_filing)
    ms_before = next(ms for ms in at_fa.multiselect if ms.key == "fa_selected_labels")
    assert len(ms_before.value) == 2
    sel_all_cb = next(cb for cb in at_fa.checkbox if cb.key == "fa_select_all_cb")
    sel_all_cb.check().run(timeout=20)
    assert not at_fa.exception
    ms_after = next(ms for ms in at_fa.multiselect if ms.key == "fa_selected_labels")
    assert len(ms_after.value) == 5

    # 3. Human Review: test real Correct Value action validating note requirement then succeeding
    at_rev = _run_view(_review)
    open_tasks_before = fetch_review_tasks(status="OPEN", db_path=db_file)
    assert len(open_tasks_before) == 1
    task_id = open_tasks_before[0]["task_id"]

    # Clicking Correct Value without a note renders helpful error banner instead of crashing
    correct_btn = next(b for b in at_rev.button if b.key == f"btn_correct_{task_id}")
    correct_btn.click().run(timeout=20)
    assert not at_rev.exception
    assert len(fetch_review_tasks(status="OPEN", db_path=db_file)) == 1

    # Now enter corrected SEC figure + audit justification and apply Correct Value
    corr_field = next(ti for ti in at_rev.text_input if ti.key == f"corr_{task_id}")
    note_field = next(ta for ta in at_rev.text_area if ta.key == f"note_{task_id}")
    corr_field.set_value("93736000000")
    note_field.set_value("Updated Net Income to match 10-K statement of operations.")
    correct_btn = next(b for b in at_rev.button if b.key == f"btn_correct_{task_id}")
    correct_btn.click().run(timeout=20)
    assert not at_rev.exception
    assert any("Decision saved" in s.value for s in at_rev.success)

    # Verify SQLite persisted original + corrected value and closed the open task
    assert fetch_review_tasks(status="OPEN", db_path=db_file) == []
    resolved = fetch_review_tasks(status="CORRECTED", db_path=db_file)
    assert any(r["task_id"] == task_id and str(r["resolved_decimal"]) == "93736000000" for r in resolved)

    # Subsequent append-only amendment from Human Review UI creates a new audit record
    amend_note_field = next(ta for ta in at_rev.text_area if ta.key == "hr_amend_note")
    amend_val_field = next(ti for ti in at_rev.text_input if ti.key == "hr_amend_val")
    amend_val_field.set_value("93750000000")
    amend_note_field.set_value("Subsequent footnote adjustment for test verification.")
    amend_btn = next(b for b in at_rev.button if b.key == "btn_record_amendment")
    amend_btn.click().run(timeout=20)
    assert not at_rev.exception
    assert any("Appended audit record" in s.value for s in at_rev.success)

    # 4. Accuracy Report
    _run_view(_accuracy)

    # 5. Audit Trail: verify hash-chain button, tamper-evident notice, sorting, telemetry toggle, and filters
    at_aud = _run_view(_audit)
    assert any("not absolutely tamper-proof" in i.value.lower() for i in at_aud.info)
    for filter_key in (
        "audit_filter_company",
        "audit_filter_date",
        "audit_filter_decision",
        "audit_filter_metric",
        "audit_sort_order",
    ):
        assert any(sb.key == filter_key for sb in at_aud.selectbox)

    sb_sort = next(sb for sb in at_aud.selectbox if sb.key == "audit_sort_order")
    sb_sort.select("Oldest First").run(timeout=20)
    assert not at_aud.exception

    cb_tel = next(cb for cb in at_aud.checkbox if cb.key == "audit_include_telemetry")
    cb_tel.check().run(timeout=20)
    assert not at_aud.exception

    sb_decision = next(sb for sb in at_aud.selectbox if sb.key == "audit_filter_decision")
    sb_decision.select("CORRECTED").run(timeout=20)
    assert not at_aud.exception

    verify_btn = next(b for b in at_aud.button if b.label == "Re-Verify Audit Hash Chain")
    verify_btn.click().run(timeout=20)
    assert not at_aud.exception
    assert any("Cryptographic chain verified" in s.value for s in at_aud.success)


def test_overview_resume_and_accuracy_eval_buttons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Overview Resume Workflow and Accuracy Report Evaluate vs. SEC Facts UI actions."""
    settings, db_file = _patch_ui_db(monkeypatch, tmp_path)
    # Point SEC cache dir at repository cache so real SEC Company Facts resolve offline/cached
    settings.sec.cache_dir = str((PROJECT_ROOT / "data" / "cache" / "sec").resolve())

    import finova_labs.evaluation as eval_mod
    import finova_labs.workflow as wf_mod

    monkeypatch.setattr(eval_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(wf_mod, "get_settings", lambda: settings)

    from finova_labs.database import fetch_audit_events, fetch_audit_run
    from finova_labs.audit import verify_audit_chain
    from finova_labs.sec_client import SecEdgarClient
    from finova_labs.settings import ConfidenceSettings
    from finova_labs.workflow import start_audit_workflow, submit_review_decision

    client = SecEdgarClient(settings=settings)
    bundle = client.fetch_latest_10k_bundle("AAPL", persist=True, db_path=db_file)
    outcome = start_audit_workflow(
        filing=bundle.latest_10k,
        company_facts=bundle.company_facts.facts,
        include_html=False,
        confidence_settings=ConfidenceSettings(auto_approve_threshold=0.95),
        db_path=db_file,
    )
    assert outcome.paused is True

    # Resolve escalated review tasks with auto_resume=False so Overview exposes Resume Workflow button
    open_tasks = fetch_review_tasks(run_id=outcome.run_id, status="OPEN", db_path=db_file)
    assert open_tasks
    for t in open_tasks:
        submit_review_decision(
            task_id=t["task_id"],
            action="APPROVE",
            reviewer_note="Verified against real AAPL SEC 10-K data.",
            reviewer="pytest",
            auto_resume=False,
            db_path=db_file,
        )

    def _overview():
        from finova_labs.views import render_overview_page
        render_overview_page()

    at_ov = _run_view(_overview)
    resume_btn = next(b for b in at_ov.button if (b.key or "") == f"overview_resume_{outcome.run_id}")
    resume_btn.click().run(timeout=20)
    assert not at_ov.exception
    assert len(at_ov.success) >= 1

    run_after = fetch_audit_run(outcome.run_id, db_path=db_file)
    assert run_after is not None and run_after["status"] == "COMPLETED"

    def _accuracy():
        from finova_labs.views import render_accuracy_report_page
        render_accuracy_report_page()

    at_acc = _run_view(_accuracy)
    eval_btn = next(b for b in at_acc.button if b.label == "Evaluate vs. SEC Facts")
    eval_btn.click().run(timeout=20)
    assert not at_acc.exception
    assert any("Evaluated 1 audit run(s)" in s.value for s in at_acc.success)

    events = fetch_audit_events(run_id=outcome.run_id, db_path=db_file, limit=200)
    acc_events = [e for e in events if e["event_type"] == "ACCURACY_EVALUATED"]
    assert acc_events
    assert acc_events[0]["ticker"] == "AAPL"
    assert acc_events[0]["accession_number"] == bundle.latest_10k.accession_number
    valid, _, reason = verify_audit_chain(db_path=db_file)
    assert valid, f"Audit chain broken: {reason}"


def test_beginner_guided_experience_tour_and_safe_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify welcome panel, 5-screen guided tour, 7-stage indicator, tooltips, and safe vs confirmed reset."""
    _, db_file = _patch_ui_db(monkeypatch, tmp_path)
    _seed_sample_data(db_file)

    def _overview():
        from finova_labs.views import render_overview_page
        render_overview_page()

    at_ov = _run_view(_overview)
    all_md = "\n".join(m.value for m in at_ov.markdown)
    # First-launch welcome banner + 7-stage progress indicator + persistent sidebar instructions
    assert "Welcome to FinovaLabs" in all_md
    for stage_text in (
        "Select company",
        "Retrieve 10-K",
        "Extract metrics",
        "Validate",
        "Review exceptions",
        "Compare with SEC facts",
        "View audit report",
    ):
        assert stage_text in all_md

    # Persistent 'How to use FinovaLabs' expander exists with numbered steps
    assert any(exp.label == "How to use FinovaLabs" for exp in at_ov.expander)

    # Start guided tour from Welcome panel and walk one screen at a time across all 5 views
    start_btn = next(b for b in at_ov.button if b.key == "welcome_start_tour")
    start_btn.click().run(timeout=20)
    assert not at_ov.exception
    expected_screens = [
        "Screen 1 of 5: Overview",
        "Screen 2 of 5: Filing Analysis",
        "Screen 3 of 5: Human Review",
        "Screen 4 of 5: Accuracy Report",
        "Screen 5 of 5: Audit Trail",
    ]
    for idx, marker in enumerate(expected_screens):
        page_md = "\n".join(m.value for m in at_ov.markdown)
        assert marker in page_md, f"Expected tour marker '{marker}' at step {idx}"
        next_btn = next(b for b in at_ov.button if b.key == "tour_next_overview")
        next_btn.click().run(timeout=20)
        assert not at_ov.exception
    assert any("Guided tour complete" in s.value for s in at_ov.success)

    # Safe UI reset must preserve 100% of SQLite audit runs and metrics
    from finova_labs.database import fetch_dashboard_summary
    before_summary = fetch_dashboard_summary(db_path=db_file)
    assert before_summary["total_runs"] >= 1

    dismiss_btn = next(b for b in at_ov.button if b.key == "welcome_dismiss_btn")
    dismiss_btn.click().run(timeout=20)
    assert not any("Welcome to FinovaLabs" in m.value for m in at_ov.markdown)

    ui_reset_btn = next(b for b in at_ov.button if b.key == "ov_reset_ui_only")
    ui_reset_btn.click().run(timeout=20)
    assert not at_ov.exception
    assert any("Welcome to FinovaLabs" in m.value for m in at_ov.markdown)
    after_ui_reset = fetch_dashboard_summary(db_path=db_file)
    assert after_ui_reset["total_runs"] == before_summary["total_runs"]
    assert after_ui_reset["audit_events"] == before_summary["audit_events"]

    # Destructive reset button must stay disabled unless BOTH checkbox & exact phrase are supplied
    wipe_btn_locked = next(b for b in at_ov.button if b.key == "ov_btn_wipe_db")
    assert wipe_btn_locked.disabled is True

    wipe_cb = next(cb for cb in at_ov.checkbox if cb.key == "ov_wipe_confirm_cb")
    wipe_cb.check().run(timeout=20)
    assert next(b for b in at_ov.button if b.key == "ov_btn_wipe_db").disabled is True

    wipe_txt = next(ti for ti in at_ov.text_input if ti.key == "ov_wipe_confirm_text")
    wipe_txt.set_value("RESET FINOVALABS").run(timeout=20)
    wipe_btn_unlocked = next(b for b in at_ov.button if b.key == "ov_btn_wipe_db")
    assert wipe_btn_unlocked.disabled is False
    wipe_btn_unlocked.click().run(timeout=20)
    assert not at_ov.exception

    after_confirmed_wipe = fetch_dashboard_summary(db_path=db_file)
    assert after_confirmed_wipe["total_runs"] == 0
    assert after_confirmed_wipe["audit_events"] == 0



