"""Page view renderers for FinovaLabs multipage navigation."""

from __future__ import annotations

from decimal import Decimal
import json
from typing import Any
import uuid

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from finova_labs import PRODUCT_NAME, PRODUCT_TAGLINE
from finova_labs.audit import TAMPER_EVIDENT_NOTICE, verify_audit_chain
from finova_labs.confidence import SCORING_METHOD_DOC
from finova_labs.database import (
    CORE_TABLES,
    check_db_health,
    clear_local_workspace,
    fetch_accuracy_evaluations,
    fetch_audit_events,
    fetch_dashboard_summary,
    fetch_extracted_metrics,
    fetch_filing_metadata,
    fetch_recoverable_workflows,
    fetch_review_tasks,
    fetch_runs,
    fetch_validation_results,
)
from finova_labs.evaluation import (
    evaluate_run_against_company_facts,
    summarize_accuracy_evaluations,
)
from finova_labs.exceptions import ConfigurationError
from finova_labs.extractor import extract_metrics_for_filing
from finova_labs.filing_manager import (
    CompanyRetrievalOutcome,
    get_supported_company_options,
    retrieve_selected_companies,
)
from finova_labs.logging_config import get_logger
from finova_labs.metric_mapping import get_approved_metrics
from finova_labs.reporting import (
    build_accuracy_report_csv,
    build_accuracy_report_json,
    build_report_metadata,
)
from finova_labs.sec_client import FilingMetadata, SecEdgarClient
from finova_labs.settings import Settings, get_settings, resolve_sec_user_agent
from finova_labs.workflow import (
    resume_audit_workflow,
    start_audit_workflow,
    submit_review_decision,
    submit_subsequent_review_correction,
)
from finova_labs.ui import (
    LOGO_SVG,
    MARK_MINI_SVG,
    TOOLTIP_CHECKPOINT,
    TOOLTIP_CONFIDENCE,
    TOOLTIP_EVIDENCE,
    TOOLTIP_PERIOD,
    TOOLTIP_UNIT,
    TOOLTIP_VALIDATION,
    _LOGO_SVG,
    _MARK_MINI_SVG,
    apply_design_system,
    flash_feedback,
    humanize_status,
    navigate_button,
    render_analyst_glossary_strip,
    render_empty_state,
    render_error_banner,
    render_field_tooltips_popover,
    render_flash_feedback,
    render_footer,
    render_guided_tour_panel,
    render_info_card,
    render_metric_cards,
    render_next_action_box,
    render_page_header,
    render_plotly_chart,
    render_status_table,
    render_welcome_panel,
    render_work_status_strip,
    render_workflow_stepper,
    reset_ui_session_state,
    safe_execute,
    stretch_width_kwargs,
)

logger = get_logger("views")


def _get_ui_session_id() -> str:
    """Return a stable Streamlit UI session identifier for append-only audit attribution."""
    if "fl_session_id" not in st.session_state:
        st.session_state["fl_session_id"] = f"ui-{uuid.uuid4().hex[:12]}"
    return str(st.session_state["fl_session_id"])


def _format_decimal_metric(
    decimal_str: str | None,
    fallback_float: float | None,
    unit: str = "USD",
) -> str:
    raw = decimal_str if decimal_str is not None else (
        str(fallback_float) if fallback_float is not None else None
    )
    if raw is None:
        return "—"
    try:
        dec = Decimal(raw)
    except Exception:
        return raw
    if unit == "USD/shares":
        return f"${dec:,.2f} / sh"
    if unit.upper() == "USD":
        return f"${dec:,.0f}" if dec == dec.to_integral_value() else f"${dec:,.2f}"
    return f"{dec:,.2f} {unit}"


def _status_tone_for_extraction(status: str) -> str:
    mapping = {
        "EXTRACTED": "success",
        "AMBIGUOUS": "warning",
        "MISSING": "neutral",
    }
    return mapping.get(status.upper(), "neutral")


def _status_tone_for_review(status: str) -> str:
    mapping = {
        "AUTO_APPROVED": "success",
        "APPROVED": "success",
        "CORRECTED": "info",
        "REVIEW_REQUIRED": "warning",
        "OPEN": "warning",
        "REJECTED": "danger",
    }
    return mapping.get(status.upper(), "neutral")


def _status_tone_for_validation(status: str) -> str:
    mapping = {
        "PASS": "success",
        "WARNING": "warning",
        "FAIL": "danger",
        "NOT_APPLICABLE": "neutral",
    }
    return mapping.get(status.upper(), "neutral")


def _status_tone_for_run(status: str) -> str:
    mapping = {
        "COMPLETED": "success",
        "COMPLETED_WITH_REJECTIONS": "warning",
        "RUNNING": "info",
        "INTERRUPTED": "warning",
        "PAUSED_FOR_REVIEW": "warning",
        "FAILED": "danger",
    }
    return mapping.get(status.upper(), "neutral")


def _format_confidence(score: float | None) -> str:
    return f"{score:.1%}" if score is not None else "—"


def _format_number(value: float | None, unit: str = "USD") -> str:
    if value is None:
        return "—"
    if unit.upper() == "USD":
        return f"${value:,.2f}"
    return f"{value:,.2f} {unit}"


def _bootstrap_page(
    section_name: str,
    *,
    active_step: int = 1,
) -> tuple[Settings | None, dict[str, Any] | None]:
    """Load validated settings, apply sidebar context, and fetch live posture summary."""
    settings = safe_execute(get_settings, "configuration loading")
    if settings is None:
        apply_design_system(section_name, db_status_label="Config Error")
        return None, None
    summary = safe_execute(fetch_dashboard_summary, "workspace posture query")
    active_ticker = st.session_state.get("fl_active_ticker")
    open_cnt = int((summary or {}).get("open_reviews") or 0)
    parts = [f"Company: {active_ticker}" if active_ticker else "No company selected yet"]
    parts.append(f"{open_cnt} pending review(s)" if open_cnt else "No pending reviews")
    apply_design_system(
        section_name,
        db_status_label="Audit Store Connected",
        context_summary=" • ".join(parts),
    )
    st.session_state["fl_current_step"] = active_step
    return settings, summary


def _render_stepper_from_summary(active_step: int, summary: dict[str, Any] | None) -> None:
    s = summary or {}
    eval_count = int(s.get("evaluations") or s.get("total_evaluations") or 0)
    if eval_count == 0 and s.get("evaluable_evaluations"):
        eval_count = int(s.get("evaluable_evaluations") or 0)
    open_reviews = int(s.get("open_reviews") or 0)
    paused_runs = int(s.get("paused_runs") or 0)
    interrupted_runs = int(s.get("interrupted_runs") or 0)
    failed_checks = int(s.get("failed_validations") or 0)
    completed_runs = int(s.get("completed_runs") or 0)
    resolved_reviews = int(s.get("resolved_reviews") or 0)

    render_workflow_stepper(
        active_step,
        companies_count=int(s.get("total_companies") or 0),
        filings_count=int(s.get("retrieved_filings") or 0),
        metrics_count=int(s.get("extracted_metrics") or 0),
        validations_count=int(s.get("validation_checks") or 0),
        failed_checks=failed_checks,
        runs_count=int(s.get("total_runs") or 0),
        open_reviews=open_reviews,
        resolved_reviews=resolved_reviews,
        evaluations_count=eval_count,
        events_count=int(s.get("audit_events") or s.get("audit_events_count") or 0),
    )
    render_work_status_strip(
        pending_count=open_reviews + paused_runs + interrupted_runs,
        completed_count=completed_runs,
        failed_count=failed_checks,
        human_decisions_count=resolved_reviews,
    )


def render_overview_page() -> None:
    """Render the FinovaLabs operational audit workspace backed strictly by real database records."""
    settings, summary = _bootstrap_page("Start & Audit Hub", active_step=1)
    if settings is None:
        render_footer()
        return

    health = safe_execute(check_db_health, "database health check")
    filings = safe_execute(lambda: fetch_filing_metadata(limit=25), "SEC filings query") or []
    runs = safe_execute(lambda: fetch_runs(limit=25), "recent runs query") or []
    recoverable = safe_execute(lambda: fetch_recoverable_workflows(limit=20), "recoverable workflows") or []
    open_review_tasks = safe_execute(lambda: fetch_review_tasks(status="OPEN", limit=50), "open review tasks query") or []

    db_ok = bool(health and health.get("healthy"))
    total_filings = len(filings)
    total_runs = len(runs)
    open_reviews_count = len(open_review_tasks)
    completed_runs_count = sum(1 for r in runs if r["status"] == "COMPLETED")
    interrupted_runs_count = sum(
        1 for w in recoverable
        if w["status"] in ("INTERRUPTED", "PAUSED_FOR_REVIEW", "RUNNING", "PENDING")
    )
    failed_checks = int((summary or {}).get("failed_validations") or 0)
    resolved_reviews_count = int((summary or {}).get("resolved_reviews") or 0)
    eval_denom = int((summary or {}).get("evaluations") or (summary or {}).get("evaluable_evaluations") or 0)

    if total_filings == 0:
        posture_label, posture_tone = "Ready to Start • Select Company", "info"
        ov_stage = 1
    elif total_runs == 0:
        posture_label, posture_tone = f"{total_filings} 10-K(s) Ready for Audit", "info"
        ov_stage = 3
    elif open_reviews_count > 0:
        posture_label, posture_tone = f"{open_reviews_count} Pending Analyst Review(s)", "warning"
        ov_stage = 5
    elif recoverable:
        posture_label, posture_tone = "Saved Audit Ready to Finish", "info"
        ov_stage = 5
    elif eval_denom == 0 and total_runs > 0:
        posture_label, posture_tone = "Ready for Final SEC Report", "info"
        ov_stage = 6
    else:
        posture_label, posture_tone = ("All Audits Up to Date", "success") if db_ok else ("Workspace Attention Needed", "warning")
        ov_stage = 7

    render_page_header(
        title=f"{PRODUCT_NAME} Operational Audit Workspace",
        subtitle="Operational command center: initiate filings, monitor real compliance checkpoints, and resolve reviews.",
        status_label=posture_label,
        status_tone=posture_tone,
    )
    _render_stepper_from_summary(ov_stage, summary)
    render_flash_feedback()

    # 1. Concise Welcome and Primary Action: Start a new audit
    render_welcome_panel(allow_dismiss=True, primary_label="Start a new audit", primary_url="filing-analysis")
    render_guided_tour_panel("overview")

    # 2. Audit Workflow Status Area with Next Important Action Visually Obvious
    resumable_ready = [
        w for w in recoverable
        if w["status"] in ("INTERRUPTED", "RUNNING", "PENDING") or int(w.get("open_review_count", 0)) == 0
    ]
    if total_filings == 0:
        ov_status = "Your audit workspace is clean and ready. No company filings have been downloaded yet."
        ov_next = "Click 'Start a new audit' on the right to choose a company and pull its latest SEC Form 10-K."
        ov_expect = "FinovaLabs fetches authentic annual filings from SEC EDGAR and prepares them for metric extraction."
        next_label, next_target = "Start a new audit ->", "filing-analysis"
    elif total_runs == 0:
        ov_status = f"You have {total_filings} downloaded Form 10-K filing(s) ready for extraction and accounting validation."
        ov_next = "Click 'Start Extraction & Checks ->' to gather the 8 standardized financial figures and verify rules."
        ov_expect = "Extracts figures with exact quotes, calculates certainty scores, and runs equation checks."
        next_label, next_target = "Start Extraction & Checks ->", "filing-analysis"
    elif open_reviews_count > 0:
        ov_status = f"{open_reviews_count} item(s) require analyst sign-off before the audit can proceed ({failed_checks} failed accounting check(s))."
        ov_next = "Click 'Resolve Pending Reviews ->' to compare each flagged figure against its 10-K quote and approve, correct, or reject it."
        ov_expect = "Analyst decision and audit justification are recorded permanently while preserving original values."
        next_label, next_target = f"Resolve {open_reviews_count} Pending Review(s) ->", "human-review"
    elif resumable_ready:
        ov_status = f"{len(resumable_ready)} saved filing audit(s) have cleared all review checkpoints and are ready to finalize."
        ov_next = "Click 'Resume Saved Audit ->' to finish processing without repeating completed extraction steps."
        ov_expect = "FinovaLabs continues from the checkpoint and prepares the audit for SEC benchmark comparison."
        next_label, next_target = "Review Saved Audits ->", "human-review"
    elif eval_denom == 0:
        ov_status = f"All {total_runs} filing audit(s) have passed review sign-off with zero pending items."
        ov_next = "Click 'Obtain Final SEC Report ->' to compare your figures against official SEC Company Facts and export reports."
        ov_expect = "Produces line-by-line accuracy comparison, coverage breakdown, and downloadable CSV/JSON audit reports."
        next_label, next_target = "Obtain Final SEC Report ->", "accuracy-report"
    else:
        ov_status = f"{total_runs} audit(s) completed and {eval_denom} figures verified against official SEC filings."
        ov_next = "Click 'Inspect Audit Trail ->' to review all analyst decisions, or click 'Start a new audit' to audit another company."
        ov_expect = "Complete chronological ledger with SHA-256 integrity verification, original amounts, and corrected values."
        next_label, next_target = "Inspect Audit Trail ->", "audit-trail"

    with st.container(border=True):
        ac_left, ac_right = st.columns([3, 1.25])
        with ac_left:
            st.markdown(f"**Current Operational Status:** {ov_status}")
            render_next_action_box(next_action=ov_next, expected_result=ov_expect)
        with ac_right:
            navigate_button(
                next_label,
                next_target,
                key="ov_primary_next_cta",
                primary=True,
                help_text="Take the primary operational next step in your audit workflow.",
            )
            render_field_tooltips_popover()

    # 3. Interrupted Workflows Ready to Resume
    if recoverable:
        st.markdown(
            f'<div class="fl-section-title">Interrupted Workflows Ready to Resume ({len(recoverable)})</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Every step is checkpointed in SQLite so restarting FinovaLabs resumes right where you stopped without repeating completed stages."
        )
        rec_rows = [
            [
                w["run_id"],
                f"{w.get('ticker') or w.get('company_name') or w['cik']} ({w.get('accession_number') or '—'})",
                w.get("current_stage") or "—",
                str(w.get("open_review_count", 0)),
                (humanize_status(w["status"]), _status_tone_for_run(w["status"])),
            ]
            for w in recoverable
        ]
        render_status_table(
            headers=["Audit ID", "Company / Filing", "Saved Step", "Pending Reviews", "Status"],
            rows=rec_rows,
            right_align_cols={3},
            min_width="680px",
        )
        for w in recoverable:
            open_cnt = int(w.get("open_review_count", 0))
            if w["status"] in ("INTERRUPTED", "RUNNING", "PENDING") or open_cnt == 0:
                if st.button(
                    f"Resume Workflow {w['run_id']} ({w.get('current_stage') or humanize_status(w['status'])})",
                    key=f"overview_resume_{w['run_id']}",
                    type="secondary",
                    help="Continues this saved audit from where it stopped without repeating finished steps.",
                ):
                    with st.spinner(f"Continuing saved audit {w['run_id']}..."):
                        outcome = safe_execute(
                            lambda rid=w["run_id"]: resume_audit_workflow(rid),
                            "workflow resume",
                        )
                    if outcome is not None:
                        flash_feedback(
                            "success",
                            f"Saved audit `{outcome.run_id}` finished cleanly -> `{humanize_status(outcome.status)}`.",
                        )
                        st.rerun()
            else:
                r_col1, r_col2 = st.columns([3, 1])
                with r_col1:
                    st.warning(
                        f"Audit `{w['run_id']}` is paused with **{open_cnt}** pending review(s). Resolve them before finalizing."
                    )
                with r_col2:
                    navigate_button(
                        "Review Now ->",
                        "human-review",
                        key=f"ov_jump_hr_{w['run_id']}",
                        primary=False,
                    )

    # 4. Pending Human Reviews
    if open_review_tasks:
        st.markdown(
            f'<div class="fl-section-title">Pending Human Reviews ({len(open_review_tasks)})</div>',
            unsafe_allow_html=True,
        )
        st.caption("Figures below 90% certainty or with failed accounting checks pause safely for analyst sign-off.")
        rev_rows = [
            [
                t.get("ticker") or t.get("cik") or "—",
                t.get("metric_name") or "—",
                t.get("reason") or "Flagged for manual review",
                _format_decimal_metric(t.get("normalized_decimal"), t.get("raw_value"), t.get("unit") or "USD"),
                (humanize_status(t.get("status") or "OPEN"), "warning"),
            ]
            for t in open_review_tasks[:10]
        ]
        render_status_table(
            headers=["Company", "Metric", "Review Reason", "Extracted Value", "Status"],
            rows=rev_rows,
            right_align_cols={3},
            min_width="680px",
        )
        p_c1, p_c2 = st.columns([3, 1.25])
        with p_c1:
            st.info(f"**{len(open_review_tasks)} item(s)** require analyst sign-off before these audits can proceed to the final report.")
        with p_c2:
            navigate_button(
                f"Resolve {len(open_review_tasks)} Review(s) ->",
                "human-review",
                key="ov_resolve_reviews_cta",
                primary=True,
                help_text="Open the Human Review queue to approve, correct, or reject pending figures.",
            )

    # 5. Recent Audit Activity
    if runs:
        st.markdown('<div class="fl-section-title">Recent Audit Activity</div>', unsafe_allow_html=True)
        rows = [
            [
                f"{r.get('ticker') or r['cik']}",
                r.get("accession_number") or r["run_id"],
                r["form_type"],
                r.get("current_stage") or "—",
                _format_confidence(r.get("overall_confidence")),
                (humanize_status(r["status"]), _status_tone_for_run(r["status"])),
            ]
            for r in runs[:10]
        ]
        render_status_table(
            headers=["Company", "Filing Ref", "Form", "Saved Step", "Confidence", "Status"],
            rows=rows,
            right_align_cols={4},
            min_width="680px",
        )
        r_act_c1, r_act_c2 = st.columns([3, 1.25])
        with r_act_c1:
            sel_run_id = st.selectbox(
                "Select an audit to inspect results:",
                options=[r["run_id"] for r in runs[:10]],
                format_func=lambda rid: next(
                    (f"{r.get('ticker') or r['cik']} • Stage: {r.get('current_stage') or '—'} • {humanize_status(r['status'])} ({rid})" for r in runs if r["run_id"] == rid),
                    str(rid),
                ),
                key="ov_run_quick_sel",
            )
        with r_act_c2:
            if st.button(
                "Inspect Audit Results ->",
                key="ov_btn_inspect_run",
                type="secondary",
                help="Inspect the extracted figures and review results for this run.",
                **stretch_width_kwargs(st.button),
            ):
                target_r = next((r for r in runs if r["run_id"] == sel_run_id), None)
                if target_r:
                    st.session_state["fl_active_ticker"] = target_r.get("ticker")
                    st.session_state["fl_active_accession"] = target_r.get("accession_number")
                pages_map = st.session_state.get("fl_pages")
                target_page = "accuracy-report" if (target_r and target_r.get("status") == "COMPLETED") else "filing-analysis"
                if isinstance(pages_map, dict) and target_page in pages_map:
                    st.switch_page(pages_map[target_page])
                else:
                    st.rerun()
    else:
        render_empty_state(
            title="No company audits started yet",
            description=(
                "FinovaLabs works strictly with real SEC Form 10-K filings and never invents numbers. "
                "Start an audit to retrieve filings, extract 8 standardized figures, and validate accounting rules."
            ),
            badge_label="Ready to Begin",
            next_step="Click 'Start a new audit' above to select your first company.",
        )

    # 6. Small Recent Filings Table
    if filings:
        st.markdown(f'<div class="fl-section-title">Recent SEC 10-K Filings ({len(filings)})</div>', unsafe_allow_html=True)
        filing_rows = [
            [
                f"{f.get('ticker') or f['cik']} — {f.get('company_name') or 'Public Issuer'}",
                f.get("form_type") or "10-K",
                f"FY {f['fiscal_year']}" if f.get("fiscal_year") else (f.get("reporting_period") or f.get("filing_date") or "Annual"),
                (humanize_status(f.get("retrieval_status") or "RETRIEVED"), "success"),
                (f.get("fetched_at") or f.get("filing_date") or "—")[:19],
            ]
            for f in filings[:10]
        ]
        render_status_table(
            headers=["Company", "Form", "Filing Period", "Status", "Last Updated"],
            rows=filing_rows,
            min_width="680px",
        )
        f_act_c1, f_act_c2 = st.columns([3, 1.25])
        with f_act_c1:
            sel_filing_accn = st.selectbox(
                "Select a filing to inspect or start audit:",
                options=[f.get("accession_number") for f in filings[:10]],
                format_func=lambda a: next(
                    (f"{f.get('ticker')} • {f.get('form_type') or '10-K'} ({f.get('fiscal_year') or f.get('filing_date')}) • Accn: {a}" for f in filings if f.get("accession_number") == a),
                    str(a),
                ),
                key="ov_filing_quick_sel",
            )
        with f_act_c2:
            if st.button(
                "Audit Selected 10-K ->",
                key="ov_btn_audit_filing",
                type="primary",
                help="Jump directly to Filing Analysis with this company filing active.",
                **stretch_width_kwargs(st.button),
            ):
                target_f = next((f for f in filings if f.get("accession_number") == sel_filing_accn), None)
                if target_f:
                    st.session_state["fl_active_ticker"] = target_f.get("ticker")
                    st.session_state["fl_active_accession"] = target_f.get("accession_number")
                pages_map = st.session_state.get("fl_pages")
                if isinstance(pages_map, dict) and "filing-analysis" in pages_map:
                    st.switch_page(pages_map["filing-analysis"])
                else:
                    st.rerun()
    elif not runs:
        render_empty_state(
            title="No SEC filings in workspace",
            description=(
                "Choose from Apple, Microsoft, Alphabet, Amazon, or Walmart in Filing Analysis "
                "to retrieve an authentic SEC Form 10-K."
            ),
            badge_label="Workspace Ready",
            next_step="Click 'Start a new audit' above to select your first company.",
        )

    # 7. System Maintenance & Audit Store Integrity
    with st.expander("System Settings, Safe Restart & Workspace Maintenance", expanded=(not db_ok)):
        col_left, col_right = st.columns([3, 1])
        with col_left:
            if health is not None:
                size_kb = health["size_bytes"] / 1024
                render_info_card(
                    title="Audit Store & Policy Rules",
                    body=(
                        f"Storage: {health['db_path']} (SQLite {health['sqlite_version']}, {size_kb:.1f} KB). "
                        f"Logs: {settings.log_file}. Auto-approve threshold ≥ {settings.confidence.auto_approve_threshold:.0%}, "
                        f"YoY alert ±{settings.validation.yoy_change_alert_threshold:.0%}."
                    ),
                    badge_label=f"{len(CORE_TABLES)}/{len(CORE_TABLES)} Tables Ready" if db_ok else "Schema Incomplete",
                    badge_tone="success" if db_ok else "danger",
                )
        with col_right:
            if st.button("Verify DB Health", type="secondary", **stretch_width_kwargs(st.button)):
                with st.spinner("Checking audit store integrity..."):
                    recheck = safe_execute(check_db_health, "live database health check")
                if recheck and recheck["healthy"]:
                    st.success(f"SQLite OK ({recheck['sqlite_version']})")
                elif recheck:
                    st.error(f"Missing tables: {', '.join(recheck['missing_tables'])}")

        st.markdown("---")
        sr_c1, sr_c2 = st.columns(2)
        with sr_c1:
            st.markdown("**Safe UI Reset (Keeps All Saved Audits)**")
            st.caption(
                "Refreshing or restarting FinovaLabs never deletes downloaded filings, human decisions, or audit history. "
                "Use this button only to reopen the Welcome banner, restart the guided tour, and clear screen filters."
            )
            if st.button(
                "Reset UI & Restart Welcome / Tour",
                key="ov_reset_ui_only",
                help="Non-destructive: resets only screen state and tour preferences.",
                **stretch_width_kwargs(st.button),
            ):
                reset_ui_session_state()
                flash_feedback(
                    "info",
                    "Screen filters, welcome panel, and guided tour were reset safely. Saved audits remain intact.",
                )
                st.rerun()

        with sr_c2:
            st.markdown("**Clear Local Workspace Data (Explicit Confirmation Required)**")
            st.caption(
                "Saved compliance records are never deleted automatically. Use this only if you explicitly want to "
                "clear all local filings, reviews, and decision history."
            )
            wipe_cb = st.checkbox(
                "I confirm I want to permanently delete all local filings, metrics, review decisions, evaluations, and audit history.",
                value=False,
                key="ov_wipe_confirm_cb",
            )
            wipe_phrase = st.text_input(
                "Type RESET FINOVALABS to unlock clear action",
                value="",
                key="ov_wipe_confirm_text",
                placeholder="RESET FINOVALABS",
            ).strip()
            wipe_unlocked = wipe_cb and wipe_phrase == "RESET FINOVALABS"
            if st.button(
                "Permanently Clear Local SQLite Data",
                key="ov_btn_wipe_db",
                disabled=not wipe_unlocked,
                help="Requires both the confirmation checkbox and typing RESET FINOVALABS.",
                **stretch_width_kwargs(st.button),
            ):
                removed = safe_execute(clear_local_workspace, "confirmed SQLite workspace reset")
                if removed is not None:
                    reset_ui_session_state()
                    total_removed = sum(removed.values())
                    flash_feedback(
                        "warning",
                        f"Confirmed local workspace reset removed {total_removed} record(s).",
                    )
                    st.rerun()

    render_footer()


def render_filing_analysis_page() -> None:
    """Render the Filing Analysis page with plain-English 10-K retrieval, extraction, and checks."""
    settings, summary = _bootstrap_page("Select Company & 10-K", active_step=2)
    if settings is None:
        render_footer()
        return

    runs = safe_execute(lambda: fetch_runs(limit=50), "audit runs query") or []
    filings = safe_execute(lambda: fetch_filing_metadata(limit=50), "SEC filing metadata query") or []
    supported = get_supported_company_options()

    fa_stage = 1 if not filings else (2 if not runs else 4)
    render_page_header(
        title="Select Company & 10-K",
        subtitle="Pick a public company, pull its latest SEC Form 10-K filing, extract 8 core financial figures, and verify accounting rules.",
        status_label=f"{len(filings)} 10-K Filing(s) Downloaded" if filings else "Step 1: Pick Company",
        status_tone="success" if filings else "info",
    )
    _render_stepper_from_summary(fa_stage, summary)
    render_flash_feedback()
    render_guided_tour_panel("filing-analysis")

    if not filings:
        fa_next = "Step 1 below: choose one or more companies and click 'Retrieve Latest 10-K Filings'."
        fa_expect = "FinovaLabs pulls the latest annual Form 10-K directly from SEC EDGAR and unlocks Step 2."
    elif not runs:
        fa_next = "Step 2 below: choose your downloaded filing and click 'Extract 8 Core Financial Metrics'."
        fa_expect = "Standardized USD and Diluted EPS figures appear with 10-K quotes, certainty scores, and accounting validation checks."
    else:
        fa_next = "Review the extracted figures, quotes, and check results in Step 3 below, or click the highlighted next-step button."
        fa_expect = "Items under 90% certainty or with failed accounting checks pause safely for Human Review; passing runs move to Final SEC Report."

    fa_guide_l, fa_guide_r = st.columns([3.4, 1.0])
    with fa_guide_l:
        render_next_action_box(next_action=fa_next, expected_result=fa_expect)
    with fa_guide_r:
        render_field_tooltips_popover()

    try:
        ua_display = resolve_sec_user_agent(settings, require_real_email=True)
        ua_ok = True
    except ConfigurationError as exc:
        ua_display = str(exc)
        ua_ok = False
        render_error_banner(
            title="SEC EDGAR Contact Email Required",
            message="Set FINOVALABS_SEC_CONTACT_EMAIL to a valid email in .env before retrieving live SEC filings.",
            hint=exc.hint,
        )

    # Step 1: Select Companies & Retrieve Real SEC 10-K
    st.markdown('<div class="fl-section-title">Step 1 · Select Companies & Download Latest SEC 10-K</div>', unsafe_allow_html=True)
    option_map = {c.display_name: c.ticker for c in supported}
    all_labels = list(option_map.keys())
    if "fa_selected_labels" not in st.session_state:
        st.session_state["fa_selected_labels"] = all_labels[:2]

    def _sync_select_all() -> None:
        if st.session_state.get("fa_select_all_cb"):
            st.session_state["fa_selected_labels"] = list(all_labels)
        else:
            st.session_state["fa_selected_labels"] = all_labels[:1]

    retrieve_btn_type = "primary" if not filings else "secondary"

    with st.container(border=True):
        col_sel, col_opts, col_btn = st.columns([3, 1, 1.3])
        with col_sel:
            selected_labels = st.multiselect(
                "Choose public companies to audit",
                options=all_labels,
                key="fa_selected_labels",
                help="Select one or more supported companies. FinovaLabs looks up their official SEC identifiers live.",
            )
        with col_opts:
            st.checkbox(
                "Select all 5 companies",
                value=len(st.session_state["fa_selected_labels"]) == len(all_labels),
                key="fa_select_all_cb",
                on_change=_sync_select_all,
            )
            force_refresh = st.checkbox(
                "Re-download fresh copy",
                value=False,
                help="Skip the saved local copy and pull a fresh Form 10-K from SEC EDGAR.",
            )
        with col_btn:
            retrieve_clicked = st.button(
                "Retrieve Latest 10-K Filings",
                type=retrieve_btn_type,
                disabled=not ua_ok,
                help="Downloads the latest official SEC Form 10-K metadata and financial facts for the selected companies.",
                **stretch_width_kwargs(st.button),
            )

        with st.expander("SEC Connection & Cache Details", expanded=False):
            st.caption(
                f"SEC Contact Header: `{ua_display}` • Speed Limit: `{settings.sec.max_requests_per_second} req/s` • "
                f"Timeout: `{settings.sec.request_timeout_seconds}s` • Cache Folder: `{settings.cache_path}`"
            )

        if retrieve_clicked:
            if not selected_labels:
                st.warning("Select at least one company before retrieving filings.")
            else:
                selected_tickers = [option_map[lbl] for lbl in selected_labels]
                progress_bar = st.progress(0.0)
                with st.status("Connecting to SEC EDGAR...", expanded=True) as status_box:
                    def _on_progress(idx: int, total: int, ticker: str) -> None:
                        status_box.write(f"Looking up official SEC record and latest 10-K for **{ticker}** ({idx}/{total})...")
                        progress_bar.progress((idx - 1) / total)

                    outcomes = retrieve_selected_companies(
                        tickers=selected_tickers,
                        force_refresh=force_refresh,
                        on_progress=_on_progress,
                    )
                    progress_bar.progress(1.0)
                    st.session_state["last_retrieval_outcomes"] = [o.model_dump() for o in outcomes]
                    st.session_state["fl_active_ticker"] = selected_tickers[0]

                    succeeded = sum(1 for o in outcomes if o.retrieval_status == "RETRIEVED")
                    failed = len(outcomes) - succeeded
                    if failed == 0:
                        status_box.update(
                            label=f"Downloaded {succeeded}/{len(outcomes)} latest 10-K filing(s) from SEC EDGAR.",
                            state="complete",
                            expanded=False,
                        )
                        flash_feedback(
                            "success",
                            f"Downloaded {succeeded}/{len(outcomes)} latest Form 10-K filing(s). Next: select a filing below and click 'Extract 8 Core Financial Metrics'.",
                        )
                        st.rerun()
                    else:
                        status_box.update(
                            label=f"Completed with {succeeded} downloaded and {failed} failed.",
                            state="error",
                            expanded=True,
                        )
                filings = safe_execute(lambda: fetch_filing_metadata(limit=50), "SEC filing metadata query") or []

    last_outcomes_raw = st.session_state.get("last_retrieval_outcomes")
    if last_outcomes_raw:
        last_outcomes = [CompanyRetrievalOutcome(**item) for item in last_outcomes_raw]
        for err_item in [o for o in last_outcomes if o.retrieval_status != "RETRIEVED"]:
            render_error_banner(
                title=f"{err_item.company_name} ({err_item.ticker}) retrieval failed",
                message=err_item.error_message or "SEC request failed.",
                hint=err_item.error_hint,
            )

    if filings:
        with st.expander(f"Downloaded 10-K Filings Ready in Workspace ({len(filings)})", expanded=False):
            filing_rows = [
                [
                    f.get("company_name") or "—",
                    f.get("ticker") or "—",
                    f["cik"],
                    f["form_type"],
                    f["filing_date"],
                    str(f["fiscal_year"]) if f.get("fiscal_year") else "—",
                    f["accession_number"],
                    (humanize_status(f.get("retrieval_status") or "RETRIEVED"), "success"),
                ]
                for f in filings
            ]
            render_status_table(
                headers=["Company", "Ticker", "SEC ID (CIK)", "Form", "Filing Date", "Fiscal Year", "Filing Number", "Status"],
                rows=filing_rows,
                right_align_cols={5},
            )

    # Step 2: Select Filing & Start Processing
    st.markdown('<div class="fl-section-title">Step 2 · Extract 8 Financial Figures & Run Accounting Checks</div>', unsafe_allow_html=True)
    selected_accn: str | None = None
    selected_filing_row: dict[str, Any] | None = None
    if filings:
        company_choices = sorted({f.get("ticker") or f["cik"] for f in filings})
        sel_col1, sel_col2 = st.columns([1, 3])
        with sel_col1:
            filter_options = ["All Companies", *company_choices]
            pref_ticker = st.session_state.get("fl_active_ticker")
            default_filter_idx = filter_options.index(pref_ticker) if pref_ticker in filter_options else 0
            filter_ticker = st.selectbox(
                "Filter by Company",
                filter_options,
                index=default_filter_idx,
                key="fa_company_filter",
            )
        scoped_filings = (
            filings
            if filter_ticker == "All Companies"
            else [f for f in filings if (f.get("ticker") or f["cik"]) == filter_ticker]
        )
        filing_options = {
            f"{f.get('company_name') or f['cik']} ({f.get('ticker') or f['cik']}) — {f['form_type']} FY{f.get('fiscal_year') or '—'} | {f['accession_number']}": f
            for f in scoped_filings
        }
        with sel_col2:
            chosen_label = st.selectbox(
                "Choose a downloaded Form 10-K filing to analyze",
                list(filing_options.keys()),
                key="fa_filing_selector",
            )
        selected_filing_row = filing_options[chosen_label]
        selected_accn = selected_filing_row["accession_number"]
        st.session_state["fl_active_ticker"] = selected_filing_row.get("ticker") or selected_filing_row["cik"]
        st.session_state["fl_active_accession"] = selected_accn

        existing_runs = [r for r in runs if r.get("accession_number") == selected_accn]
        latest_run = existing_runs[0] if existing_runs else None
        if latest_run is not None:
            st.session_state["fl_active_run_id"] = latest_run["run_id"]

        render_info_card(
            title=f"{selected_filing_row.get('company_name') or selected_filing_row['cik']} ({selected_filing_row.get('ticker') or '—'}) — Form {selected_filing_row['form_type']}",
            body=(
                f"SEC ID: {selected_filing_row['cik']} • Filing Number: {selected_filing_row['accession_number']} • "
                f"Filed: {selected_filing_row['filing_date']} • Period End: {selected_filing_row.get('reporting_period') or '—'} • "
                f"Fiscal Year: {selected_filing_row.get('fiscal_year') or '—'}"
            ),
            badge_label=humanize_status(latest_run["status"]) if latest_run else "Ready to Extract",
            badge_tone=_status_tone_for_run(latest_run["status"]) if latest_run else "info",
        )

        act_c1, act_c2, act_c3 = st.columns([2.2, 1.5, 1.3])
        with act_c1:
            include_html = st.checkbox(
                "Cross-check full 10-K report tables for exact quotes & scale (Recommended)",
                value=True,
                help=f"{TOOLTIP_EVIDENCE} Also enables: {TOOLTIP_UNIT}",
            )
        with act_c2:
            force_new_run = False
            if latest_run is not None:
                force_new_run = st.checkbox(
                    "Start a fresh re-audit",
                    value=False,
                    help=f"By default, FinovaLabs safely reuses the saved audit run without duplicating work. {TOOLTIP_CHECKPOINT}",
                    key=f"fa_confirm_rerun_{selected_accn}",
                )
        with act_c3:
            needs_extraction_cta = (latest_run is None) or force_new_run
            extract_label = "Re-Run Filing Audit" if force_new_run else "Extract 8 Core Financial Metrics"
            run_clicked = st.button(
                extract_label,
                type="primary" if needs_extraction_cta else "secondary",
                help=f"{TOOLTIP_CONFIDENCE} {TOOLTIP_VALIDATION} {TOOLTIP_CHECKPOINT}",
                **stretch_width_kwargs(st.button),
            )

        if run_clicked:
            def _run_workflow() -> Any:
                client = SecEdgarClient(settings=settings)
                meta = FilingMetadata(
                    cik=selected_filing_row["cik"],
                    ticker=selected_filing_row.get("ticker"),
                    company_name=selected_filing_row.get("company_name"),
                    accession_number=selected_filing_row["accession_number"],
                    form_type=selected_filing_row["form_type"],
                    filing_date=selected_filing_row["filing_date"],
                    reporting_period=selected_filing_row.get("reporting_period"),
                    fiscal_year=selected_filing_row.get("fiscal_year"),
                    primary_document=selected_filing_row.get("primary_document"),
                    filing_url=selected_filing_row["filing_url"],
                    submissions_url=selected_filing_row["submissions_url"],
                    companyfacts_url=selected_filing_row["companyfacts_url"],
                )
                cf = client.get_company_facts(meta.cik)
                html_txt: str | None = None
                if include_html:
                    html_txt, _, _ = client.get_filing_html(
                        filing_url=meta.filing_url,
                        cik=meta.cik,
                        accession_number=meta.accession_number,
                        primary_document=meta.primary_document,
                    )
                return start_audit_workflow(
                    filing=meta,
                    company_facts=cf.facts,
                    html_text=html_txt,
                    include_html=include_html,
                    force_new_run=force_new_run,
                    confidence_settings=settings.confidence,
                    validation_settings=settings.validation,
                )

            with st.status("Extracting financial figures, scoring certainty, and running accounting checks...", expanded=True) as ext_status:
                wf_outcome = safe_execute(_run_workflow, "audited workflow execution")
                if wf_outcome is not None:
                    st.session_state["fl_active_run_id"] = wf_outcome.run_id
                    if wf_outcome.paused:
                        ext_status.update(
                            label=(
                                f"Audit {wf_outcome.run_id} PAUSED for Review: "
                                f"{len(wf_outcome.auto_approved_metrics)} auto-approved, "
                                f"{wf_outcome.open_task_count} item(s) need analyst sign-off."
                            ),
                            state="complete",
                            expanded=False,
                        )
                        flash_feedback(
                            "warning",
                            f"Audit `{wf_outcome.run_id}` paused with {wf_outcome.open_task_count} item(s) needing analyst review. Open '3. Resolve Human Reviews' to sign off.",
                        )
                    else:
                        msg_prefix = "Loaded saved audit" if getattr(wf_outcome, "reused_existing_run", False) else "Completed audit"
                        ext_status.update(
                            label=f"{msg_prefix} {wf_outcome.run_id}: {len(wf_outcome.auto_approved_metrics)} figure(s) auto-approved.",
                            state="complete",
                            expanded=False,
                        )
                        flash_feedback(
                            "success",
                            f"{msg_prefix} `{wf_outcome.run_id}` ({humanize_status(wf_outcome.status)}): {len(wf_outcome.auto_approved_metrics)} auto-approved.",
                        )
                    st.rerun()
                else:
                    ext_status.update(label="Filing analysis failed.", state="error", expanded=True)

        # Single obvious next-step CTA once this filing has been processed
        if latest_run is not None and not force_new_run:
            if latest_run["status"] == "PAUSED_FOR_REVIEW":
                n1, n2 = st.columns([3, 1.2])
                with n1:
                    st.warning(
                        f"**Pending Analyst Sign-Off:** Audit `{latest_run['run_id']}` has paused with flagged items waiting for review."
                    )
                with n2:
                    navigate_button(
                        "Resolve Pending Reviews ->",
                        "human-review",
                        key=f"fa_next_hr_{selected_accn}",
                        primary=True,
                    )
            elif latest_run["status"] in ("COMPLETED", "COMPLETED_WITH_REJECTIONS"):
                n1, n2 = st.columns([3, 1.2])
                with n1:
                    st.success(
                        f"**Ready for Final Report ({humanize_status(latest_run['status'])}):** All required sign-offs for this filing are complete."
                    )
                with n2:
                    navigate_button(
                        "Obtain Final SEC Report ->",
                        "accuracy-report",
                        key=f"fa_next_acc_{selected_accn}",
                        primary=True,
                    )
    else:
        render_empty_state(
            title="Download a 10-K filing in Step 1 first",
            description=(
                "No SEC Form 10-K filings have been downloaded yet. Select one or more companies above and click "
                "'Retrieve Latest 10-K Filings' to begin."
            ),
            badge_label="Step 1 Required",
            next_step="Step 2 unlocks automatically once filing metadata is saved.",
        )

    metrics = (
        safe_execute(
            lambda: fetch_extracted_metrics(accession_number=selected_accn, limit=100),
            "extracted metrics query",
        )
        if selected_accn
        else None
    )
    validations = (
        safe_execute(
            lambda: fetch_validation_results(accession_number=selected_accn, limit=100),
            "financial validations query",
        )
        if selected_accn
        else None
    )

    # Step 3: Inspect Extracted Metrics, Evidence & Validations
    st.markdown('<div class="fl-section-title">Step 3 · Inspect Extracted Figures, Quotes & Validation Checks</div>', unsafe_allow_html=True)
    render_analyst_glossary_strip(expanded=(bool(metrics) and not runs))

    tab_metrics, tab_vals, tab_spec = st.tabs(
        [
            f"Extracted Figures ({len(metrics or [])})",
            f"Accounting Checks ({len(validations or [])})",
            "8-Metric Audit Guide & Scoring Formula",
        ]
    )

    with tab_metrics:
        if metrics:
            extracted_cnt = sum(1 for m in metrics if m.get("extraction_status") == "EXTRACTED")
            auto_cnt = sum(1 for m in metrics if m.get("review_status") == "AUTO_APPROVED")
            pending_cnt = sum(1 for m in metrics if m.get("review_status") == "REVIEW_REQUIRED")
            human_cnt = sum(1 for m in metrics if m.get("review_status") in ("APPROVED", "CORRECTED", "REJECTED"))
            failed_cnt = sum(1 for m in metrics if m.get("validation_status") == "FAIL")
            render_metric_cards(
                [
                    {"label": "Figures Found", "value": f"{extracted_cnt} / {len(metrics)}", "detail": "Non-missing annual figures"},
                    {"label": "Auto-Approved (Done)", "value": str(auto_cnt), "detail": "Passed ≥90% certainty & checks"},
                    {"label": "Pending / Failed Checks", "value": f"{pending_cnt} / {failed_cnt}", "detail": "Waiting review / failed accounting rule"},
                    {
                        "label": "Human Signed Off",
                        "value": str(human_cnt),
                        "detail": f"Avg certainty: {_format_confidence(sum(float(m.get('confidence_score') or 0.0) for m in metrics) / len(metrics))}",
                    },
                ]
            )

            rows = [
                [
                    m["metric_name"],
                    _format_decimal_metric(
                        m.get("normalized_decimal"),
                        m.get("normalized_value"),
                        m.get("unit") or "USD",
                    ),
                    f"{m.get('unit') or 'USD'} ({m.get('scale_factor') or 1:,}x)",
                    f"{m.get('fiscal_period') or 'FY'} {m.get('fiscal_year') or ''} ({m.get('period_end') or '—'})",
                    _format_confidence(m.get("confidence_score")),
                    (
                        humanize_status(m.get("validation_status") or "PENDING"),
                        _status_tone_for_validation(m.get("validation_status") or "PENDING"),
                    ),
                    (
                        humanize_status(m.get("review_status") or "NOT_REQUIRED"),
                        _status_tone_for_review(m.get("review_status") or "NOT_REQUIRED"),
                    ),
                ]
                for m in metrics
            ]
            render_status_table(
                headers=["Financial Metric", "Standardized Value", "Unit & Scale", "Reporting Period", "Confidence", "Accounting Check", "Work Status"],
                rows=rows,
                right_align_cols={1, 4},
            )

            conf_rows = [
                {
                    "Metric": m["metric_name"],
                    "Confidence (%)": round((m.get("confidence_score") or 0.0) * 100.0, 2),
                    "Work Status": humanize_status(m.get("review_status") or "NOT_REQUIRED"),
                }
                for m in metrics
            ]
            if conf_rows:
                conf_df = pd.DataFrame(conf_rows)
                fig_conf = px.bar(
                    conf_df,
                    x="Confidence (%)",
                    y="Metric",
                    orientation="h",
                    color="Work Status",
                    color_discrete_map={
                        "Auto-Approved": "#0E5A3E",
                        "Analyst Approved": "#1E4B9A",
                        "Analyst Corrected": "#3163BA",
                        "Pending Review": "#854D0E",
                        "Analyst Rejected": "#8B1D1D",
                        "Not Required": "#596779",
                    },
                )
                fig_conf.add_vline(
                    x=settings.confidence.auto_approve_threshold * 100.0,
                    line_dash="dash",
                    line_color="#0C1B2E",
                    annotation_text=f"Auto-Approve Cutoff ({settings.confidence.auto_approve_threshold:.0%})",
                )
                fig_conf.update_xaxes(range=[0, 108])
                render_plotly_chart(
                    fig_conf,
                    title="Certainty Score vs. 90% Auto-Approval Cutoff",
                    key=f"fa_conf_chart_{selected_accn or 'all'}",
                    height=310,
                )

            with st.expander("10-K Source Quotes (Evidence) & 5-Factor Confidence Breakdown", expanded=False):
                for m in metrics:
                    conf_pct = _format_confidence(m.get("confidence_score"))
                    st.markdown(
                        f"**{m['metric_name']}** — {humanize_status(m.get('extraction_status'))} | "
                        f"SEC Concept: `{m.get('xbrl_concept') or 'None'}` | "
                        f"As Printed in Filing: `{m.get('raw_value') or '—'}` | Certainty: **{conf_pct}**"
                    )
                    st.markdown(
                        f"<div class='fl-evidence-box'><strong>Where Found:</strong> {m.get('evidence_location') or '—'}<br>"
                        f"<strong>10-K Quote:</strong> {m.get('source_evidence') or 'No verbatim quote captured.'}<br>"
                        f"<strong>Official SEC Link:</strong> {m.get('source_url') or '—'}</div>",
                        unsafe_allow_html=True,
                    )
                    raw_comp = m.get("confidence_components_json")
                    if raw_comp:
                        try:
                            comp_data = json.loads(raw_comp)
                            f_rows = [
                                [
                                    f.get("label") or f.get("factor") or "—",
                                    f"{f.get('weight', 0):.0%}",
                                    f"{f['raw_score']:.2f}" if f.get("raw_score") is not None else "Unavailable",
                                    f"+{f.get('contribution', 0):.3f}",
                                    (f.get("status") or "UNAVAILABLE", "success" if f.get("status") == "PASS" else ("warning" if f.get("status") == "PARTIAL" else ("danger" if f.get("status") == "FAIL" else "neutral"))),
                                    f.get("reason") or "",
                                ]
                                for f in comp_data.get("factors", [])
                            ]
                            if f_rows:
                                render_status_table(
                                    headers=["Factor", "Weight", "Score", "Points", "Status", "Why"],
                                    rows=f_rows,
                                    right_align_cols={1, 2, 3},
                                )
                        except ValueError:
                            pass
                    raw_cands = m.get("candidates_json")
                    if raw_cands:
                        try:
                            cands = json.loads(raw_cands)
                            if len(cands) > 1 or m.get("extraction_status") == "AMBIGUOUS":
                                st.caption(f"Alternative figures found in filing ({len(cands)}):")
                                for c in cands[:5]:
                                    st.code(
                                        f"{c.get('concept')} | standardized={c.get('normalized_value')} {c.get('reported_unit')} "
                                        f"| printed={c.get('raw_value')} (scale={c.get('scale_factor')}x) | {c.get('evidence_location')}",
                                        language="text",
                                    )
                        except ValueError:
                            pass
        else:
            render_empty_state(
                title="No extracted figures for this filing yet",
                description="FinovaLabs never invents placeholder metrics. Click 'Extract 8 Core Financial Metrics' in Step 2 to read this 10-K.",
                badge_label="Awaiting Extraction",
                next_step="Standardized figures, units, reporting periods, 10-K quotes, and certainty ratings will appear here.",
            )

    with tab_vals:
        if validations:
            val_rows = []
            for v in validations:
                pct_str = "—"
                if v.get("variance_pct") is not None:
                    try:
                        pct_str = f"{Decimal(str(v['variance_pct'])):+.2%}"
                    except Exception:
                        pct_str = str(v["variance_pct"])
                val_rows.append(
                    [
                        v["rule_name"].replace("_", " ").title(),
                        v["metric_name"],
                        (humanize_status(v["status"]), _status_tone_for_validation(v["status"])),
                        pct_str,
                        v["explanation"],
                    ]
                )
            render_status_table(
                headers=["Accounting Rule", "Line Item / Scope", "Result", "Difference %", "Plain-English Explanation"],
                rows=val_rows,
                right_align_cols={3},
            )
            with st.expander("Check Inputs & Allowed Tolerances", expanded=False):
                for v in validations:
                    st.markdown(
                        f"**{v['rule_name'].replace('_', ' ').title()} — {v['metric_name']}** (`{humanize_status(v['status'])}`) • "
                        f"Allowed Tolerance: `{v.get('tolerance_used') or '—'}` • Sent to Review: `{'Yes' if v.get('escalated') else 'No'}`"
                    )
                    if v.get("input_metric_refs_json"):
                        st.code(v["input_metric_refs_json"], language="json")
        else:
            render_empty_state(
                title="No accounting checks run yet",
                description="Extract figures in Step 2 to run the Balance Sheet equation, Segment total check, and Year-over-Year swing checks.",
                badge_label="Pending Extraction",
                next_step="Checks clearly separate Passed, Alert / Review, Failed Check, and Not Applicable.",
            )

    with tab_spec:
        approved_specs = get_approved_metrics()
        spec_rows = [
            [
                spec.name,
                spec.period_type.title(),
                spec.expected_unit,
                spec.sign_convention.title(),
                ", ".join(spec.xbrl_concepts[:2]) + ("…" if len(spec.xbrl_concepts) > 2 else ""),
                ("Supported", "success"),
            ]
            for spec in approved_specs
        ]
        render_status_table(
            headers=["Financial Metric", "Period Type", "Standard Unit", "Sign Rule", "Standard SEC Tags", "Coverage"],
            rows=spec_rows,
        )
        st.caption(
            f"Scoring Policy v{settings.confidence.scoring_version} • "
            f"Auto-Approval Threshold: ≥ {settings.confidence.auto_approve_threshold:.0%}"
        )
        st.code(SCORING_METHOD_DOC, language="text")

    render_footer()


def render_human_review_page() -> None:
    """Render the plain-English Human Review queue backed by saved escalation tasks."""
    settings, summary = _bootstrap_page("Resolve Human Reviews", active_step=3)
    if settings is None:
        render_footer()
        return

    all_tasks = safe_execute(lambda: fetch_review_tasks(limit=100), "review tasks query") or []
    open_tasks = [t for t in all_tasks if t["status"] == "OPEN"]
    open_count = len(open_tasks)
    resolved_count = len(all_tasks) - open_count
    failed_checks_count = int((summary or {}).get("failed_validations") or 0)

    render_page_header(
        title="Resolve Human Reviews",
        subtitle="Check flagged financial figures side-by-side with exact 10-K quotes, then Approve, Correct, or Reject each pending item.",
        status_label=f"{open_count} Pending Review(s)" if open_count else "All Reviews Resolved",
        status_tone="warning" if open_count else "success",
    )
    _render_stepper_from_summary(5, summary)
    render_flash_feedback()
    render_guided_tour_panel("human-review")

    if open_count > 0:
        hr_next = "Open Pending Item #1 below, compare the extracted figure against the 10-K quote on the left, and choose Approve, Correct Value, or Reject."
        hr_expect = "Your signed-off figure and note are permanently saved alongside the original number, unblocking the final SEC report."
    else:
        hr_next = "Zero pending reviews remain. Click the highlighted button below to generate your Final SEC Report."
        hr_expect = "Compares both initial figures and your signed-off decisions directly against official SEC filings."

    hr_g1, hr_g2 = st.columns([3.4, 1.0])
    with hr_g1:
        render_next_action_box(next_action=hr_next, expected_result=hr_expect)
    with hr_g2:
        render_field_tooltips_popover()

    render_analyst_glossary_strip(expanded=False)

    conf = settings.confidence
    val = settings.validation
    render_metric_cards(
        [
            {"label": "Pending Analyst Action", "value": str(open_count), "detail": "Prioritized at top of queue below"},
            {"label": "Signed Off (Human Decisions)", "value": str(resolved_count), "detail": "Saved with original figure intact"},
            {"label": "Failed Accounting Checks", "value": str(failed_checks_count), "detail": f"Auto-approve requires pass & ≥ {conf.auto_approve_threshold:.0%} certainty"},
            {"label": "Year-over-Year Alert", "value": f"±{val.yoy_change_alert_threshold:.0%}", "detail": f"Segment tolerance ±{val.segment_reconciliation_tolerance:.1%}"},
        ]
    )

    recoverable_runs = safe_execute(lambda: fetch_recoverable_workflows(limit=50), "recoverable workflow check") or []
    resumable_runs = [
        r for r in recoverable_runs
        if r["status"] in ("INTERRUPTED", "RUNNING", "PENDING")
        or (r["status"] == "PAUSED_FOR_REVIEW" and int(r.get("open_review_count", 0)) == 0)
    ]

    if open_count == 0 and not resumable_runs:
        n1, n2 = st.columns([3, 1.2])
        with n1:
            if all_tasks:
                st.success("**All Pending Items Resolved:** Every flagged financial figure now has a saved analyst decision.")
            else:
                st.info("**Review Queue Clear:** No flagged items are waiting for analyst sign-off right now.")
        with n2:
            if (summary or {}).get("total_runs", 0) > 0:
                navigate_button("Obtain Final SEC Report ->", "accuracy-report", key="hr_next_acc", primary=True)
            else:
                navigate_button("Select Company & 10-K ->", "filing-analysis", key="hr_next_fa", primary=True)

    status_filter = st.selectbox(
        "Filter Review Queue by Decision Status",
        ["ALL", "OPEN", "APPROVED", "CORRECTED", "REJECTED"],
        help="Show all items, only Pending Review (OPEN), or completed Human Decisions.",
    )
    filtered = (
        all_tasks
        if status_filter == "ALL"
        else [t for t in all_tasks if t["status"] == status_filter]
    )

    # Pending items always shown FIRST when filter permits
    if status_filter in {"ALL", "OPEN"}:
        if open_tasks:
            st.markdown('<div class="fl-section-title">Pending Work · Escalated Items Awaiting Sign-Off</div>', unsafe_allow_html=True)
            for idx, t in enumerate(open_tasks):
                unit_label = t.get("unit") or "USD"
                currency_label = t.get("currency") or "USD"
                orig_display = _format_decimal_metric(
                    t.get("normalized_decimal"),
                    t.get("normalized_value"),
                    unit_label,
                )
                company_display = (
                    f"{t.get('company_name') or t.get('cik') or '—'} "
                    f"({t.get('ticker') or t.get('cik') or '—'})"
                )
                period_display = (
                    f"{t.get('fiscal_period') or 'FY'} {t.get('fiscal_year') or '—'} | "
                    f"{t.get('period_start') or 'Year-End Balance'} → {t.get('period_end') or '—'}"
                )
                header = (
                    f"[PENDING #{idx + 1}] {company_display} • {t.get('metric_name') or '—'} • "
                    f"Extracted: {orig_display} • Confidence: {_format_confidence(t.get('confidence_score'))}"
                )
                with st.expander(header, expanded=(idx == 0)):
                    st.warning(f"**Why Flagged for Analyst Review:** {t['reason']}")
                    col_evidence, col_decision = st.columns([1.15, 1.0])

                    with col_evidence:
                        st.markdown("**Extracted Figure & 10-K Filing Evidence**")
                        st.markdown(
                            f"**Company:** {company_display}  \n"
                            f"**Metric:** {t.get('metric_name') or '—'}  \n"
                            f"**Original Extracted Value:** `{orig_display}` (as printed: `{t.get('raw_value') or '—'}`)  \n"
                            f"**<abbr class='fl-tip' title='{TOOLTIP_PERIOD}'>Reporting Period</abbr>:** `{period_display}` | "
                            f"**<abbr class='fl-tip' title='{TOOLTIP_UNIT}'>Unit</abbr>:** `{unit_label} ({currency_label})`  \n"
                            f"**<abbr class='fl-tip' title='{TOOLTIP_CONFIDENCE}'>Confidence</abbr>:** `{_format_confidence(t.get('confidence_score'))}` "
                            f"(Auto-approve ≥ `{_format_confidence(t.get('confidence_threshold'))}`) | "
                            f"**<abbr class='fl-tip' title='{TOOLTIP_VALIDATION}'>Accounting Check</abbr>:** `{humanize_status(t.get('validation_status') or 'PENDING')}`  \n"
                            f"**Source Filing:** `Form {t.get('form_type') or '10-K'}` `{t.get('accession_number') or '—'}` "
                            f"(Filed `{t.get('filing_date') or '—'}`)  \n"
                            f"**Official SEC URL:** {t.get('source_url') or '—'}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"<div class='fl-evidence-box'><strong><abbr class='fl-tip' title='{TOOLTIP_EVIDENCE}'>10-K Quote</abbr> ({t.get('evidence_location') or 'Location not recorded'}):</strong><br>"
                            f"{t.get('source_evidence') or 'No verbatim quote captured for this figure in the filing.'}</div>",
                            unsafe_allow_html=True,
                        )

                    with col_decision:
                        st.markdown("**Analyst Sign-Off & Explanation**")
                        default_corr = (
                            str(t["normalized_decimal"])
                            if t.get("normalized_decimal") is not None
                            else (str(t["normalized_value"]) if t.get("normalized_value") is not None else "")
                        )
                        corr_input = st.text_input(
                            "Corrected Value (used only if clicking 'Correct Value')",
                            value=default_corr,
                            key=f"corr_{t['task_id']}",
                            help=f"Enter the full standardized figure in {unit_label}. The original extracted number stays preserved for audit history.",
                        )
                        if default_corr and corr_input.strip() and corr_input.strip() != default_corr:
                            st.caption(f"Proposed change: `{default_corr}` -> `{corr_input.strip()}` ({unit_label})")
                        reviewer_input = st.text_input(
                            "Analyst Name / Initials",
                            value="analyst",
                            key=f"rev_{t['task_id']}",
                            help="Recorded alongside your browser session in the permanent decision log.",
                        )
                        note_input = st.text_area(
                            "Review Note / Reason (required when correcting or rejecting)",
                            placeholder="Explain how you verified this number in the 10-K report or why it should be rejected...",
                            key=f"note_{t['task_id']}",
                        )
                        st.caption(
                            "Submitting saves your decision permanently before advancing the audit."
                        )

                        act_clicked: str | None = None
                        b1, b2, b3 = st.columns(3)
                        with b1:
                            if st.button(
                                "Approve",
                                key=f"btn_approve_{t['task_id']}",
                                type="primary" if idx == 0 else "secondary",
                                help="Accept the original extracted value as verified.",
                                **stretch_width_kwargs(st.button),
                            ):
                                act_clicked = "APPROVE"
                        with b2:
                            if st.button(
                                "Correct Value",
                                key=f"btn_correct_{t['task_id']}",
                                help="Replace with the corrected value entered above (requires a short review note).",
                                **stretch_width_kwargs(st.button),
                            ):
                                act_clicked = "EDIT"
                        with b3:
                            if st.button(
                                "Reject",
                                key=f"btn_reject_{t['task_id']}",
                                help="Mark this figure as unverified / unusable (requires a short review note).",
                                **stretch_width_kwargs(st.button),
                            ):
                                act_clicked = "REJECT"

                        if act_clicked is not None:
                            try:
                                # Prevent duplicate submission if task already resolved by prior click/tab
                                latest_state = [
                                    row for row in fetch_review_tasks(limit=200)
                                    if row["task_id"] == t["task_id"]
                                ]
                                if latest_state and latest_state[0]["status"] != "OPEN":
                                    flash_feedback(
                                        "warning",
                                        f"Task `{t['task_id']}` was already signed off as `{humanize_status(latest_state[0]['status'])}` — duplicate submission prevented.",
                                    )
                                    st.rerun()

                                with st.spinner("Saving your review decision and updating audit progress..."):
                                    res = submit_review_decision(
                                        task_id=t["task_id"],
                                        action=act_clicked,
                                        reviewer_note=note_input,
                                        corrected_value=corr_input if act_clicked == "EDIT" else None,
                                        reviewer=reviewer_input,
                                        session_id=_get_ui_session_id(),
                                        decision_key=f"ui-{t['task_id']}-{act_clicked}",
                                        auto_resume=True,
                                    )
                                wf_out = res.get("workflow_outcome")
                                if wf_out:
                                    flash_feedback(
                                        "success",
                                        f"Decision saved (`{humanize_status(res['decision']['status'])}`). Audit `{wf_out['run_id']}` finished -> `{humanize_status(wf_out['status'])}`. Next: open '4. Final SEC Report'.",
                                    )
                                else:
                                    flash_feedback(
                                        "success",
                                        f"Decision saved (`{humanize_status(res['decision']['status'])}`). {res['remaining_open_for_run']} pending item(s) remain in this audit.",
                                    )
                                st.rerun()
                            except Exception as exc:
                                render_error_banner(
                                    "Review decision could not be saved",
                                    str(exc),
                                    hint="Please enter a review note when clicking Correct Value or Reject, and make sure any edited figure is numeric.",
                                )
        elif all_tasks and status_filter == "OPEN":
            render_empty_state(
                title="No pending reviews remain",
                description="All flagged figures have already been approved, corrected, or rejected by an analyst.",
                badge_label="Queue Clear",
                next_step="Switch the filter to ALL to inspect signed-off decisions, or go to '4. Final SEC Report'.",
            )

    if resumable_runs:
        st.warning(f"**Ready to Finalize ({len(resumable_runs)}):** All flagged items for this saved audit have been signed off.")
        for r in resumable_runs:
            if st.button(
                f"Resume Workflow {r['run_id']} ({humanize_status(r['status'])} @ {r.get('current_stage') or '—'})",
                key=f"resume_{r['run_id']}",
                type="primary" if open_count == 0 else "secondary",
            ):
                with st.spinner(f"Finalizing saved audit {r['run_id']}..."):
                    outcome = safe_execute(lambda rid=r["run_id"]: resume_audit_workflow(rid), "workflow resume")
                if outcome is not None:
                    flash_feedback(
                        "success",
                        f"Audit `{outcome.run_id}` finished -> `{humanize_status(outcome.status)}`.",
                    )
                    st.rerun()

    all_metrics = safe_execute(lambda: fetch_extracted_metrics(limit=200), "amendable metrics query") or []
    amendable_metrics = [m for m in all_metrics if m.get("review_status") != "REVIEW_REQUIRED"]
    if amendable_metrics:
        with st.expander("Add Subsequent Amendment to an Already-Approved Figure (Optional)", expanded=False):
            st.caption(
                "Adds a new follow-up correction entry without ever erasing earlier approvals or the original extracted figure."
            )
            metric_options = {
                m["id"]: (
                    f"{m.get('ticker') or m.get('cik')} • {m['metric_name']} "
                    f"({m.get('accession_number') or '—'}) — {humanize_status(m.get('review_status'))}"
                )
                for m in amendable_metrics
            }
            sel_amend_id = st.selectbox(
                "Choose Metric to Amend",
                options=list(metric_options.keys()),
                format_func=lambda mid: metric_options.get(mid, str(mid)),
                key="hr_amend_metric_id",
            )
            sel_m = next(m for m in amendable_metrics if m["id"] == sel_amend_id)
            m_unit = sel_m.get("unit") or "USD"
            orig_m_disp = _format_decimal_metric(sel_m.get("normalized_decimal"), sel_m.get("normalized_value"), m_unit)
            curr_m_disp = _format_decimal_metric(sel_m.get("reviewed_decimal"), sel_m.get("reviewed_value"), m_unit)
            st.markdown(
                f"**Original Extracted Value:** `{orig_m_disp}` | "
                f"**Current Final Value:** `{curr_m_disp}` | "
                f"**Audit ID:** `{sel_m.get('run_id') or 'Standalone'}`"
            )
            ac1, ac2, ac3 = st.columns([1, 2, 1])
            with ac1:
                amend_action = st.selectbox("Action", ["EDIT", "APPROVE", "REJECT"], key="hr_amend_action")
            with ac2:
                amend_val = st.text_input(
                    "Corrected Value (applied for EDIT)",
                    value=str(sel_m.get("reviewed_decimal") or sel_m.get("normalized_decimal") or ""),
                    key="hr_amend_val",
                )
            with ac3:
                amend_reviewer = st.text_input("Analyst Name", value="analyst", key="hr_amend_reviewer")
            amend_note = st.text_area(
                "Amendment Reason (required for EDIT / REJECT)",
                placeholder="Explain why you are updating this previously reviewed figure...",
                key="hr_amend_note",
            )
            if st.button("Record Append-Only Amendment", key="btn_record_amendment", type="secondary"):
                try:
                    with st.spinner("Saving follow-up decision entry..."):
                        amend_res = submit_subsequent_review_correction(
                            metric_id=sel_amend_id,
                            action=amend_action,
                            reviewer_note=amend_note,
                            corrected_value=amend_val if amend_action == "EDIT" else None,
                            reviewer=amend_reviewer,
                            session_id=_get_ui_session_id(),
                        )
                    flash_feedback(
                        "success",
                        f"Appended audit record #{amend_res['decision'].get('audit_event_id')} "
                        f"(`{humanize_status(amend_res['decision']['status'])}`). Earlier history kept intact.",
                    )
                    st.rerun()
                except Exception as exc:
                    render_error_banner("Amendment could not be saved", str(exc))

    st.markdown('<div class="fl-section-title">All Review Items & Human Decisions</div>', unsafe_allow_html=True)
    if filtered:
        rows = [
            [
                f"{t.get('ticker') or t.get('company_name') or '—'} ({t.get('accession_number') or t.get('run_id') or '—'})",
                t.get("metric_name") or "—",
                _format_decimal_metric(
                    t.get("normalized_decimal"),
                    t.get("normalized_value"),
                    t.get("unit") or "USD",
                ),
                _format_decimal_metric(
                    t.get("resolved_decimal"),
                    t.get("resolved_value"),
                    t.get("unit") or "USD",
                ),
                _format_confidence(t.get("confidence_score")),
                t["reason"],
                (humanize_status(t["status"]), _status_tone_for_review(t["status"])),
            ]
            for t in filtered
        ]
        render_status_table(
            headers=["Company / Filing", "Metric", "Original Value", "Final Value", "Confidence", "Reason Flagged", "Decision Status"],
            rows=rows,
            right_align_cols={2, 3, 4},
        )
    else:
        render_empty_state(
            title="No review items match the selected filter",
            description="Figures flagged by low certainty (<90%) or failed accounting checks appear here for analyst review.",
            badge_label="Queue Clear",
            next_step="Run a filing audit in '2. Select Company & 10-K' or change the filter above to ALL.",
        )

    render_footer()


def _status_tone_for_accuracy(status: str) -> str:
    mapping = {
        "EXACT_MATCH": "success",
        "MATCH_FOUND": "success",
        "MISMATCH": "danger",
        "UNMATCHED_RECORD": "danger",
        "PERIOD_MISMATCH": "warning",
        "UNIT_MISMATCH": "warning",
        "UNAVAILABLE_REFERENCE": "warning",
    }
    return mapping.get(status.upper(), "neutral")


def _format_pct_diff(raw_pct: Any) -> str:
    if raw_pct is None or str(raw_pct).strip() == "":
        return "N/A"
    try:
        return f"{float(raw_pct):.4f}%"
    except (TypeError, ValueError):
        return str(raw_pct)


def render_accuracy_report_page() -> None:
    """Render the plain-English Final SEC Report page for accuracy benchmarking & downloads."""
    settings, posture_summary = _bootstrap_page("Final SEC Report", active_step=4)
    if settings is None:
        render_footer()
        return

    all_runs = safe_execute(lambda: fetch_runs(limit=100), "runs query") or []
    all_evaluations = safe_execute(
        lambda: fetch_accuracy_evaluations(limit=500),
        "accuracy evaluations query",
    ) or []
    _ = build_report_metadata(report_type="company_facts_accuracy")

    render_page_header(
        title="Final SEC Report",
        subtitle=(
            "Check both the initially extracted numbers and final analyst-reviewed values against official SEC "
            "financial reports, then download CSV or JSON reports."
        ),
        status_label=f"{len(all_evaluations)} Figures Verified" if all_evaluations else "Ready to Verify",
        status_tone="success" if all_evaluations else "neutral",
    )
    _render_stepper_from_summary(6, posture_summary)
    render_flash_feedback()
    render_guided_tour_panel("accuracy-report")

    if not all_runs:
        acc_next = "Click 'Select Company & 10-K ->' below to retrieve a Form 10-K and extract figures first."
        acc_expect = "Once a company audit has been run, you can verify every figure against official SEC filings and export your final report."
    elif not all_evaluations:
        acc_next = "Choose an audit below (or 'All Audit Runs') and click 'Evaluate vs. SEC Facts'."
        acc_expect = "Shows Before-Review vs. After-Review accuracy, transparent coverage totals, interactive charts, and CSV/JSON report downloads."
    else:
        acc_next = "Download your Final CSV / JSON Reports below or click 'Inspect Decision History ->' to verify the full approval record."
        acc_expect = "Downloadable executive files plus complete traceability across every analyst approval, edit, and rejection."

    acc_g1, acc_g2 = st.columns([3.4, 1.0])
    with acc_g1:
        render_next_action_box(next_action=acc_next, expected_result=acc_expect)
    with acc_g2:
        render_field_tooltips_popover()

    render_analyst_glossary_strip(expanded=False)

    if not all_runs:
        render_info_card(
            title="Primary Next Action: Run a Company Audit First",
            body=(
                "No company audits have been started yet. Pick a company and extract figures in "
                "'2. Select Company & 10-K' before running the Final SEC Report."
            ),
            badge_label="Step 1 Required",
            badge_tone="info",
        )
        navigate_button(
            "Select Company & 10-K ->",
            "filing-analysis",
            key="acc_go_fa_empty",
            primary=True,
        )
    else:
        with st.container(border=True):
            st.markdown("**1. Verify Audited Figures Against Official SEC Reports**")
            st.caption(
                "Compares each figure strictly by Company, Line-Item Meaning, Annual Fiscal Year Period, and Unit. "
                "Accuracy Before Human Review and After Human Review are reported separately."
            )
            run_labels = {
                r["run_id"]: f"{r.get('ticker') or r['cik']} • {r.get('accession_number') or r['run_id']} ({humanize_status(r['status'])})"
                for r in all_runs
            }
            existing_eval_runs = {e["run_id"] for e in all_evaluations}
            c1, c2, c3 = st.columns([3, 1.2, 1.4])
            with c1:
                eval_target = st.selectbox(
                    "Choose company audit to verify",
                    options=["ALL_RUNS", *run_labels.keys()],
                    format_func=lambda k: "All Audit Runs" if k == "ALL_RUNS" else run_labels.get(k, k),
                    key="acc_eval_target",
                    help="Verify one completed filing audit or every audit in your workspace.",
                )
            with c2:
                force_refresh_cf = st.checkbox(
                    "Refresh SEC reference",
                    value=False,
                    key="acc_force_refresh",
                    help="Pull a fresh copy of the official SEC Company Facts database instead of using the saved local copy.",
                )
            with c3:
                run_eval_clicked = st.button(
                    "Evaluate vs. SEC Facts",
                    type="primary" if not all_evaluations else "secondary",
                    **stretch_width_kwargs(st.button),
                )

            target_will_overwrite = (
                bool(existing_eval_runs)
                if eval_target == "ALL_RUNS"
                else eval_target in existing_eval_runs
            )
            if target_will_overwrite:
                st.caption(
                    "Re-checking refreshes the comparison snapshot for those audits while keeping your human decisions and audit trail intact."
                )

            if run_eval_clicked:
                target_ids = list(run_labels.keys()) if eval_target == "ALL_RUNS" else [eval_target]
                ok_count = 0
                with st.spinner("Comparing extracted and signed-off figures against official SEC data..."):
                    for rid in target_ids:
                        res = safe_execute(
                            lambda target_rid=rid: evaluate_run_against_company_facts(
                                target_rid,
                                force_refresh=force_refresh_cf,
                                persist=True,
                            ),
                            f"SEC Company Facts evaluation for {rid}",
                        )
                        if res is not None:
                            ok_count += 1
                if ok_count:
                    flash_feedback(
                        "success",
                        f"Evaluated {ok_count} audit run(s) against SEC Company Facts and updated your Final Report.",
                    )
                    st.rerun()
                else:
                    render_error_banner(
                        "SEC comparison failed",
                        "No selected audits could be verified. Check internet connectivity or SEC Contact Email settings.",
                    )

    # Company & run filters
    company_opts = sorted({(e.get("ticker") or e.get("cik") or "UNKNOWN") for e in all_evaluations})
    run_opts = sorted({e["run_id"] for e in all_evaluations})
    if all_evaluations:
        f1, f2 = st.columns(2)
        with f1:
            sel_company = st.selectbox("Filter by Company", ["ALL", *company_opts], key="acc_filter_company")
        with f2:
            sel_run = st.selectbox("Filter by Audit ID", ["ALL", *run_opts], key="acc_filter_run")
        evaluations = [
            e for e in all_evaluations
            if (sel_company == "ALL" or (e.get("ticker") or e.get("cik") or "UNKNOWN") == sel_company)
            and (sel_run == "ALL" or e["run_id"] == sel_run)
        ]
    else:
        sel_run = "ALL"
        evaluations = []

    summary = summarize_accuracy_evaluations(evaluations)

    pre_acc_display = (
        f"{summary.pre_review_accuracy_evaluable:.1%}"
        if summary.pre_review_accuracy_evaluable is not None
        else "—"
    )
    post_acc_display = (
        f"{summary.post_review_accuracy_evaluable:.1%}"
        if summary.post_review_accuracy_evaluable is not None
        else "—"
    )
    gt_cov_display = f"{summary.ground_truth_coverage:.1%}" if summary.total_records else "—"
    non_match_total = (
        summary.pre_mismatches + summary.unmatched_record_count + summary.unavailable_reference_count
    )

    render_metric_cards(
        [
            {
                "label": "Before Human Review",
                "value": pre_acc_display,
                "detail": summary.pre_denominator_label if summary.total_records else "Initial automated match rate",
            },
            {
                "label": "After Human Review (Final)",
                "value": post_acc_display,
                "detail": (
                    f"{summary.post_denominator_label} • +{summary.human_corrected_matches} fixed by analyst"
                    if summary.total_records
                    else "Final verified match rate"
                ),
            },
            {
                "label": "SEC Reference Coverage",
                "value": gt_cov_display,
                "detail": summary.coverage_denominator_label if summary.total_records else "Figures with SEC benchmark",
            },
            {
                "label": "Failed Matches & Missing Refs",
                "value": str(non_match_total),
                "detail": (
                    f"Mismatch: {summary.pre_mismatches} | Unmatched: {summary.unmatched_record_count} | "
                    f"No SEC Ref: {summary.unavailable_reference_count}"
                ),
            },
        ]
    )

    if evaluations:
        act_c1, act_c2, _ = st.columns([1.4, 1.4, 2])
        with act_c1:
            navigate_button(
                "Inspect Decision History ->",
                "audit-trail",
                key="acc_go_audit",
                primary=True,
                help_text="Review every analyst approval, edit, and reason in chronological order.",
            )
        with act_c2:
            navigate_button(
                "Back to Human Reviews",
                "human-review",
                key="acc_go_hr",
                primary=False,
                help_text="Open pending sign-offs or submit a follow-up correction.",
            )

        with st.expander("How Accuracy & SEC Coverage Are Calculated (Plain-English Rules)", expanded=True):
            st.markdown(
                f"- **Matching Rules:** Every audited figure is matched strictly against official SEC financial "
                f"data on **Company**, **Accounting Concept**, **Annual (`FY`) Reporting Period**, and **Unit**. "
                f"Period mismatches (`{summary.period_mismatch_count}`), unit mismatches (`{summary.unit_mismatch_count}`), "
                f"and items the company omitted from SEC reference tags (`{summary.unavailable_reference_count}`) "
                f"**never count as matches**.\n"
                f"- **Before Human Review (`{pre_acc_display}`):** Measures automated extraction before any analyst fixes "
                f"(`{summary.pre_denominator_label}`, overall across all records: `{summary.pre_review_accuracy_overall:.1%}`).\n"
                f"- **After Human Review (`{post_acc_display}`):** Measures final numbers after analyst sign-off and edits "
                f"(`{summary.post_denominator_label}`, overall: `{summary.post_review_accuracy_overall:.1%}`).\n"
                f"- **SEC Reference Coverage (`{gt_cov_display}`):** Share of figures with an official SEC comparison tag "
                f"(`{summary.coverage_denominator_label}`)."
            )

        st.markdown('<div class="fl-section-title">Accuracy & Coverage Charts</div>', unsafe_allow_html=True)
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            if summary.by_company:
                comp_df = pd.DataFrame(
                    [
                        {
                            "Company": c.ticker or c.group_key,
                            "Before Review (%)": round((c.pre_review_accuracy_evaluable or 0.0) * 100.0, 2),
                            "After Review (%)": round((c.post_review_accuracy_evaluable or 0.0) * 100.0, 2),
                            "SEC Ref Coverage (%)": round(c.ground_truth_coverage * 100.0, 2),
                        }
                        for c in summary.by_company
                    ]
                )
                comp_long = comp_df.melt(
                    id_vars="Company",
                    var_name="Measure",
                    value_name="Percentage (%)",
                )
                fig_comp = px.bar(
                    comp_long,
                    x="Company",
                    y="Percentage (%)",
                    color="Measure",
                    barmode="group",
                    color_discrete_map={
                        "Before Review (%)": "#1E4B9A",
                        "After Review (%)": "#0E5A3E",
                        "SEC Ref Coverage (%)": "#596779",
                    },
                )
                fig_comp.update_xaxes(title=None)
                fig_comp.update_yaxes(range=[0, 108], title="Accuracy / Coverage (%)")
                render_plotly_chart(
                    fig_comp,
                    title="Company Accuracy: Before vs. After Human Review (%)",
                    key="acc_company_plotly",
                    height=380,
                )

        with chart_col2:
            if summary.by_metric:
                met_df = pd.DataFrame(
                    [
                        {
                            "Metric": m.group_label,
                            "Before Review (%)": round((m.pre_review_accuracy_evaluable or 0.0) * 100.0, 2),
                            "After Review (%)": round((m.post_review_accuracy_evaluable or 0.0) * 100.0, 2),
                        }
                        for m in summary.by_metric
                    ]
                )
                met_long = met_df.melt(
                    id_vars="Metric",
                    var_name="Stage",
                    value_name="Accuracy (%)",
                )
                fig_met = px.bar(
                    met_long,
                    x="Accuracy (%)",
                    y="Metric",
                    color="Stage",
                    barmode="group",
                    orientation="h",
                    color_discrete_map={
                        "Before Review (%)": "#1E4B9A",
                        "After Review (%)": "#0E5A3E",
                    },
                )
                fig_met.update_xaxes(range=[0, 108], title="Accuracy (%)")
                fig_met.update_yaxes(categoryorder="total ascending", title=None)
                render_plotly_chart(
                    fig_met,
                    title="Line-Item Accuracy: Before vs. After Human Review (%)",
                    key="acc_metric_plotly",
                    height=380,
                )

        st.markdown('<div class="fl-section-title">Accuracy by Company</div>', unsafe_allow_html=True)
        render_status_table(
            headers=[
                "Company",
                "Total",
                "With SEC Ref",
                "SEC Coverage",
                "Before Review",
                "Before %",
                "After Review",
                "Final %",
                "Analyst Fixed",
            ],
            rows=[
                [
                    c.group_label,
                    str(c.total_records),
                    str(c.evaluable_count),
                    f"{c.ground_truth_coverage:.1%}",
                    c.pre_denominator_label,
                    f"{c.pre_review_accuracy_evaluable:.1%}" if c.pre_review_accuracy_evaluable is not None else "—",
                    c.post_denominator_label,
                    f"{c.post_review_accuracy_evaluable:.1%}" if c.post_review_accuracy_evaluable is not None else "—",
                    str(c.human_corrected_matches),
                ]
                for c in summary.by_company
            ],
            right_align_cols={1, 2, 3, 4, 5, 6, 7, 8},
            min_width="780px",
        )

        st.markdown('<div class="fl-section-title">Accuracy by Financial Metric</div>', unsafe_allow_html=True)
        render_status_table(
            headers=[
                "Metric",
                "Total",
                "With SEC Ref",
                "SEC Coverage",
                "Before Review",
                "Before %",
                "After Review",
                "Final %",
                "Analyst Fixed",
            ],
            rows=[
                [
                    m.group_label,
                    str(m.total_records),
                    str(m.evaluable_count),
                    f"{m.ground_truth_coverage:.1%}",
                    m.pre_denominator_label,
                    f"{m.pre_review_accuracy_evaluable:.1%}" if m.pre_review_accuracy_evaluable is not None else "—",
                    m.post_denominator_label,
                    f"{m.post_review_accuracy_evaluable:.1%}" if m.post_review_accuracy_evaluable is not None else "—",
                    str(m.human_corrected_matches),
                ]
                for m in summary.by_metric
            ],
            right_align_cols={1, 2, 3, 4, 5, 6, 7, 8},
            min_width="780px",
        )

        st.markdown('<div class="fl-section-title">Line-by-Line SEC Comparison</div>', unsafe_allow_html=True)
        detail_rows = []
        for e in evaluations:
            unit = e.get("unit") or "USD"
            period_label = f"{e.get('fiscal_period') or 'FY'} ({e.get('period_end') or '—'})"
            pre_st = e.get("pre_status") or "UNAVAILABLE_REFERENCE"
            post_st = e.get("post_status") or "UNAVAILABLE_REFERENCE"
            detail_rows.append(
                [
                    e.get("ticker") or e.get("cik") or "—",
                    e["metric_name"],
                    e.get("xbrl_concept") or "—",
                    period_label,
                    unit,
                    _format_decimal_metric(e.get("pre_review_decimal"), e.get("extracted_value"), unit),
                    _format_decimal_metric(e.get("post_review_decimal"), None, unit),
                    _format_decimal_metric(e.get("ground_truth_decimal"), e.get("ground_truth_value"), e.get("ground_truth_unit") or unit),
                    _format_decimal_metric(e.get("pre_abs_diff"), e.get("abs_diff"), unit),
                    _format_pct_diff(e.get("pre_pct_diff")),
                    (humanize_status(pre_st), _status_tone_for_accuracy(pre_st)),
                    (humanize_status(post_st), _status_tone_for_accuracy(post_st)),
                ]
            )
        render_status_table(
            headers=[
                "Company",
                "Metric",
                "SEC Concept",
                "Reporting Period",
                "Unit",
                "Before Review",
                "Final Value",
                "SEC Reference",
                "Diff ($)",
                "Diff (%)",
                "Before Status",
                "Final Status",
            ],
            rows=detail_rows,
            right_align_cols={5, 6, 7, 8, 9},
            min_width="1120px",
        )

        with st.expander("Official SEC Reference Links & Explanations", expanded=False):
            for e in evaluations:
                st.markdown(
                    f"**{e.get('ticker') or e.get('cik')} • {e['metric_name']} (`{e['run_id']}`)** — "
                    f"SEC Link: `{e.get('reference_source_url') or 'N/A'}`  \n"
                    f"{e.get('explanation') or ''}"
                )

        st.markdown('<div class="fl-section-title">Download Final Report Files</div>', unsafe_allow_html=True)
        exp_run_id = sel_run if sel_run != "ALL" else None
        dl1, dl2 = st.columns(2)
        with dl1:
            csv_data = build_accuracy_report_csv(evaluations, run_id=exp_run_id)
            st.download_button(
                "Download Final Report (CSV for Excel)",
                data=csv_data,
                file_name=f"finovalabs_accuracy_{exp_run_id or 'all'}.csv",
                mime="text/csv",
                **stretch_width_kwargs(st.download_button),
            )
        with dl2:
            json_data = build_accuracy_report_json(evaluations, run_id=exp_run_id)
            st.download_button(
                "Download Final Report (JSON)",
                data=json_data,
                file_name=f"finovalabs_accuracy_{exp_run_id or 'all'}.json",
                mime="application/json",
                **stretch_width_kwargs(st.download_button),
            )
    else:
        render_empty_state(
            title="No SEC comparison results yet",
            description=(
                "The Final SEC Report checks your initial and signed-off figures side-by-side against official "
                "SEC data using strict company, fiscal-year, and unit matching."
            ),
            badge_label="Awaiting Verification",
            next_step="Click 'Evaluate vs. SEC Facts' above once you have completed an extraction run.",
        )

    render_footer()


def render_audit_trail_page() -> None:
    """Render the plain-English Decision History & tamper-evident Audit Trail ledger."""
    settings, posture_summary = _bootstrap_page("Decision History", active_step=5)
    if settings is None:
        render_footer()
        return

    verification = safe_execute(verify_audit_chain, "audit chain verification")
    all_events = safe_execute(lambda: fetch_audit_events(limit=500), "audit events query") or []
    all_tasks = safe_execute(lambda: fetch_review_tasks(limit=250), "review decision audit query") or []
    resolved_task_rows = [t for t in all_tasks if t["status"] != "OPEN"]
    human_event_rows = [ev for ev in all_events if ev["event_type"] == "HUMAN_REVIEW_DECISION"]

    chain_valid = bool(verification and verification[0])
    event_total = verification[1] if verification else 0
    failure_reason = verification[2] if verification else "Verification failed"

    render_page_header(
        title="Decision History & Audit Trail",
        subtitle=(
            "Review every analyst approval, correction, rejection, and audit milestone in chronological order, "
            "showing Original vs. Corrected values and record integrity status."
        ),
        status_label=(
            f"Records Verified • {event_total} Entries"
            if chain_valid
            else "Record Integrity Alert"
        ),
        status_tone="success" if chain_valid else "danger",
    )
    _render_stepper_from_summary(7, posture_summary)
    render_flash_feedback()
    render_guided_tour_panel("audit-trail")

    aud_g1, aud_g2 = st.columns([3.4, 1.0])
    with aud_g1:
        render_next_action_box(
            next_action=(
                "Filter below by Company, Date, Decision, or Metric, or click 'Re-Verify Audit Hash Chain' "
                "to confirm no earlier decision was altered or deleted."
            ),
            expected_result=(
                "Confirms chronological record integrity, shows Original vs. Corrected amounts side-by-side, "
                "and lets you export the complete compliance log as JSON."
            ),
        )
    with aud_g2:
        render_field_tooltips_popover()

    st.info(TAMPER_EVIDENT_NOTICE)

    render_metric_cards(
        [
            {
                "label": "Total Audit Entries",
                "value": str(event_total),
                "detail": "Permanent chronological record",
            },
            {
                "label": "Record Integrity Check",
                "value": "Verified" if chain_valid else "Alert Detected",
                "detail": failure_reason or "Sequential numbering & link check passed",
            },
            {
                "label": "Analyst Decisions",
                "value": str(len(human_event_rows) if human_event_rows else len(resolved_task_rows)),
                "detail": (
                    f"{sum(1 for d in human_event_rows if (d.get('decision') or '') == 'CORRECTED')} corrected • "
                    f"{sum(1 for d in human_event_rows if (d.get('decision') or '') == 'APPROVED')} approved • "
                    f"{sum(1 for d in human_event_rows if (d.get('decision') or '') == 'REJECTED')} rejected"
                    if human_event_rows
                    else (
                        f"{sum(1 for d in resolved_task_rows if d['status'] == 'CORRECTED')} corrected • "
                        f"{sum(1 for d in resolved_task_rows if d['status'] == 'APPROVED')} approved • "
                        f"{sum(1 for d in resolved_task_rows if d['status'] == 'REJECTED')} rejected"
                    )
                ),
            },
            {
                "label": "Activity Log File",
                "value": settings.logging.level,
                "detail": str(settings.log_file),
            },
        ]
    )

    btn_c1, btn_c2, btn_c3 = st.columns([1.4, 1.4, 1.2])
    with btn_c1:
        if st.button("Re-Verify Audit Hash Chain", type="primary", **stretch_width_kwargs(st.button)):
            with st.spinner("Verifying chronological record integrity..."):
                recheck = safe_execute(verify_audit_chain, "manual hash-chain verification")
            if recheck and recheck[0]:
                st.success(f"Cryptographic chain verified across {recheck[1]} event(s) (tamper-evident).")
            elif recheck:
                st.error(f"Record integrity alert: {recheck[2]}")
    with btn_c2:
        ledger_json = json.dumps(
            {
                "product": PRODUCT_NAME,
                "tagline": PRODUCT_TAGLINE,
                "security_model": "tamper-evident (sequential seq_id + SHA-256 hash chain; not absolutely tamper-proof)",
                "chain_valid": chain_valid,
                "event_count": len(all_events),
                "events": all_events,
                "reviewer_decisions": resolved_task_rows,
            },
            indent=2,
            default=str,
        )
        st.download_button(
            "Download Full Audit Log (JSON)",
            data=ledger_json,
            file_name="finovalabs_audit_trail.json",
            mime="application/json",
            **stretch_width_kwargs(st.download_button),
        )
    with btn_c3:
        navigate_button(
            "Audit Another Company ->",
            "filing-analysis",
            key="aud_go_fa",
            primary=False,
            help_text="Select a new company and download its 10-K filing.",
        )

    # Interactive filters: Company, Date (UTC), Decision, Metric, Workflow ID, Sort & System detail scope
    company_opts = sorted({
        (ev.get("ticker") or ev.get("cik"))
        for ev in all_events
        if (ev.get("ticker") or ev.get("cik"))
    })
    date_opts = sorted(
        {str(ev["created_at"])[:10] for ev in all_events if ev.get("created_at")},
        reverse=True,
    )
    decision_opts = sorted({
        (ev.get("decision") or ev["event_type"])
        for ev in all_events
        if (ev.get("decision") or ev.get("event_type"))
    })
    metric_opts = sorted({ev["metric_name"] for ev in all_events if ev.get("metric_name")})
    run_ids = sorted({ev["run_id"] for ev in all_events if ev.get("run_id")})

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        sel_company = st.selectbox("Company", ["ALL", *company_opts], key="audit_filter_company")
    with fc2:
        sel_date = st.selectbox("Date (UTC)", ["ALL", *date_opts], key="audit_filter_date")
    with fc3:
        sel_decision = st.selectbox(
            "Decision",
            ["ALL", *decision_opts],
            key="audit_filter_decision",
            help="Filter by analyst decision (APPROVED, CORRECTED, REJECTED) or audit milestone.",
        )
    with fc4:
        sel_metric = st.selectbox("Metric", ["ALL", *metric_opts], key="audit_filter_metric")

    fc5, fc6, fc7 = st.columns([1.2, 1.8, 1.0])
    with fc5:
        sel_run_id = st.selectbox("Audit Run ID", ["ALL", *run_ids], key="audit_run_id")
    with fc6:
        search_q = st.text_input(
            "Search Analyst / Filing / Reason",
            value="",
            key="audit_search",
            placeholder="e.g., analyst, 0000320193, Net Income...",
        ).strip().lower()
    with fc7:
        sort_order = st.selectbox(
            "Sort Order",
            ["Newest First", "Oldest First"],
            key="audit_sort_order",
            help="Sort entries by record number and UTC timestamp.",
        )

    include_telemetry = st.checkbox(
        "Show detailed automated check entries in full history table",
        value=False,
        key="audit_include_telemetry",
        help=(
            "When unchecked, the lower history table focuses on analyst sign-offs and major audit milestones "
            "(started, paused, completed, SEC report generated)."
        ),
    )

    if len(all_events) >= 500:
        st.caption("Showing the most recent 500 entries. Download JSON or apply filters to narrow results.")

    filtered_events = safe_execute(
        lambda: fetch_audit_events(
            run_id=None if sel_run_id == "ALL" else sel_run_id,
            company=None if sel_company == "ALL" else sel_company,
            date=None if sel_date == "ALL" else sel_date,
            decision=None if sel_decision == "ALL" else sel_decision,
            metric_name=None if sel_metric == "ALL" else sel_metric,
            limit=500,
        ),
        "filtered audit events query",
    ) or []

    if search_q:
        filtered_events = [
            ev for ev in filtered_events
            if search_q in (ev.get("event_type") or "").lower()
            or search_q in (ev.get("decision") or "").lower()
            or search_q in (ev.get("reviewer_id") or ev.get("actor") or "").lower()
            or search_q in (ev.get("session_id") or "").lower()
            or search_q in (ev.get("accession_number") or "").lower()
            or search_q in (ev.get("explanation") or "").lower()
            or search_q in (ev.get("metric_name") or "").lower()
            or search_q in (ev.get("run_id") or "").lower()
            or search_q in (ev.get("created_at") or "").lower()
            or search_q in (ev.get("payload_json") or "").lower()
        ]

    reverse_sort = sort_order == "Newest First"
    filtered_events = sorted(
        filtered_events,
        key=lambda ev: (int(ev.get("seq_id") or 0), str(ev.get("created_at") or ""), int(ev.get("event_id") or 0)),
        reverse=reverse_sort,
    )

    filtered_human_events = [
        ev for ev in filtered_events
        if ev["event_type"] == "HUMAN_REVIEW_DECISION"
    ]

    st.markdown('<div class="fl-section-title">Analyst Decisions (Permanent Before &amp; After Log)</div>', unsafe_allow_html=True)
    if filtered_human_events:
        dec_rows = [
            [
                str(ev.get("seq_id") or ev["event_id"]),
                str(ev.get("created_at") or "")[:19].replace("T", " "),
                f"{ev.get('reviewer_id') or ev.get('actor') or 'analyst'} ({(ev.get('session_id') or '—')[:12]})",
                ev.get("run_id") or "—",
                f"{ev.get('ticker') or ev.get('cik') or '—'} ({ev.get('accession_number') or '—'})",
                ev.get("metric_name") or "—",
                (humanize_status(ev.get("decision") or ev["event_type"]), _status_tone_for_review(ev.get("decision") or "")),
                ev.get("original_value") or "—",
                ev.get("corrected_value") or "—",
                ev.get("explanation") or "—",
            ]
            for ev in filtered_human_events
        ]
        render_status_table(
            headers=[
                "Record #",
                "Time (UTC)",
                "Analyst / Session",
                "Audit ID",
                "Company / Filing",
                "Metric",
                "Decision",
                "Original Value",
                "Corrected Value",
                "Reason",
            ],
            rows=dec_rows,
            right_align_cols={0, 7, 8},
        )
    else:
        render_empty_state(
            title="No analyst decisions match these filters",
            description=(
                "Every human approval, correction, rejection, and follow-up amendment adds a permanent row "
                "here showing both the original and updated figures."
            ),
            badge_label="No Decision Matches",
        )

    milestone_types = {
        "HUMAN_REVIEW_DECISION",
        "WORKFLOW_STARTED",
        "WORKFLOW_PAUSED",
        "WORKFLOW_RESUMED",
        "WORKFLOW_COMPLETED",
        "ACCURACY_EVALUATED",
    }
    ledger_events = (
        filtered_events
        if (include_telemetry or sel_decision != "ALL")
        else [ev for ev in filtered_events if ev.get("event_type") in milestone_types]
    )

    st.markdown('<div class="fl-section-title">Complete Chronological Audit History</div>', unsafe_allow_html=True)
    if not include_telemetry and sel_decision == "ALL" and len(filtered_events) > len(ledger_events):
        st.caption(
            f"Showing {len(ledger_events)} key decision & milestone record(s) ({len(filtered_events) - len(ledger_events)} "
            "routine automated check records hidden — check the box above to view every detail)."
        )

    if ledger_events:
        rows = [
            [
                str(ev.get("seq_id") or ev["event_id"]),
                str(ev["created_at"])[:19].replace("T", " "),
                ev.get("ticker") or ev.get("cik") or "—",
                ev.get("accession_number") or "—",
                ev.get("metric_name") or "—",
                humanize_status(ev.get("decision") or ev["event_type"]),
                ev.get("original_value") or "—",
                ev.get("corrected_value") or "—",
                f"{ev.get('reviewer_id') or ev['actor']} ({(ev.get('session_id') or '—')[:12]})",
                ev.get("run_id") or "—",
                f"{ev['event_hash'][:12]}…",
                ("Verified", "success"),
            ]
            for ev in ledger_events
        ]
        render_status_table(
            headers=[
                "Record #",
                "UTC Time",
                "Company",
                "Filing",
                "Metric",
                "Decision",
                "Original",
                "Corrected",
                "Analyst / Session",
                "Audit ID",
                "Integrity Link",
                "Chain",
            ],
            rows=rows,
            right_align_cols={0, 6, 7},
        )
        with st.expander("Technical Provenance & Full Integrity Link Details", expanded=False):
            for ev in ledger_events[:50]:
                st.markdown(
                    f"**Record #{ev.get('seq_id') or ev['event_id']} (`event_id={ev['event_id']}`) • "
                    f"{humanize_status(ev.get('decision') or ev['event_type'])}** (`{ev['created_at']}`) — "
                    f"Reviewer: `{ev.get('reviewer_id') or ev['actor']}` | Session: `{ev.get('session_id') or '—'}` | "
                    f"Company: `{ev.get('ticker') or ev.get('cik') or '—'}` | Filing: `{ev.get('accession_number') or '—'}` | "
                    f"Metric: `{ev.get('metric_name') or '—'}` | Audit ID: `{ev.get('run_id') or '—'}`  \n"
                    f"Reason: {ev.get('explanation') or '—'}  \n"
                    f"Original Value: `{ev.get('original_value') or '—'}` | Corrected Value: `{ev.get('corrected_value') or '—'}`  \n"
                    f"Prev Hash: `{ev['prev_hash'][:16]}…` -> Event Hash: `{ev['event_hash'][:16]}…`"
                )
                st.code(ev["payload_json"], language="json")
    else:
        render_empty_state(
            title="No matching history records found",
            description=(
                "The tamper-evident SHA-256 audit ledger is ready (tamper-evident, not absolutely tamper-proof). "
                "Events record automatically as you extract filings, verify checks, and sign off on reviews."
            ),
            badge_label="History Ready" if not all_events else "No Filter Matches",
            next_step="Adjust the filters above or enable detailed check entries.",
        )

    render_footer()

