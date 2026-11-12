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
    TOOLTIP_CHECKPOINT,
    TOOLTIP_CONFIDENCE,
    TOOLTIP_EVIDENCE,
    TOOLTIP_PERIOD,
    TOOLTIP_UNIT,
    TOOLTIP_VALIDATION,
    apply_design_system,
    flash_feedback,
    humanize_status,
    navigate_button,
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
    parts = [f"Selected: {active_ticker}" if active_ticker else "No active company"]
    parts.append(f"{open_cnt} open review(s)" if open_cnt else "Review queue clear")
    apply_design_system(
        section_name,
        db_status_label="SQLite Connected",
        context_summary=" • ".join(parts),
    )
    st.session_state["fl_current_step"] = active_step
    return settings, summary


def _render_stepper_from_summary(active_step: int, summary: dict[str, Any] | None) -> None:
    s = summary or {}
    eval_count = int(s.get("evaluations") or s.get("total_evaluations") or 0)
    if eval_count == 0 and s.get("evaluable_evaluations"):
        eval_count = int(s.get("evaluable_evaluations") or 0)
    render_workflow_stepper(
        active_step,
        companies_count=int(s.get("total_companies") or 0),
        filings_count=int(s.get("retrieved_filings") or 0),
        metrics_count=int(s.get("extracted_metrics") or 0),
        validations_count=int(s.get("validation_checks") or 0),
        runs_count=int(s.get("total_runs") or 0),
        open_reviews=int(s.get("open_reviews") or 0),
        resolved_reviews=int(s.get("resolved_reviews") or 0),
        evaluations_count=eval_count,
        events_count=int(s.get("audit_events") or s.get("audit_events_count") or 0),
    )


def render_overview_page() -> None:
    """Render the FinovaLabs Overview dashboard backed by real SQLite state."""
    settings, summary = _bootstrap_page("Overview", active_step=1)
    if settings is None:
        render_footer()
        return

    health = safe_execute(check_db_health, "database health check")
    filings = safe_execute(lambda: fetch_filing_metadata(limit=25), "SEC filings query") or []
    runs = safe_execute(lambda: fetch_runs(limit=25), "recent runs query") or []
    all_metrics = safe_execute(lambda: fetch_extracted_metrics(limit=250), "overview metrics query") or []
    recoverable = safe_execute(lambda: fetch_recoverable_workflows(limit=20), "recoverable workflows") or []

    db_ok = bool(health and health.get("healthy"))
    open_reviews = int((summary or {}).get("open_reviews") or 0)
    total_filings = int((summary or {}).get("retrieved_filings") or 0)
    total_runs = int((summary or {}).get("total_runs") or 0)
    eval_denom = int((summary or {}).get("evaluations") or (summary or {}).get("evaluable_evaluations") or 0)
    pre_matches = int((summary or {}).get("pre_exact_matches") or 0)
    post_matches = int((summary or {}).get("post_exact_matches") or 0)

    if total_filings == 0:
        posture_label, posture_tone = "Start Here • No Filings", "info"
        ov_stage = 1
    elif total_runs == 0:
        posture_label, posture_tone = f"{total_filings} Filing(s) Ready", "info"
        ov_stage = 3
    elif open_reviews > 0:
        posture_label, posture_tone = f"{open_reviews} Escalation(s) Pending", "warning"
        ov_stage = 5
    elif recoverable:
        posture_label, posture_tone = "Checkpoint Ready to Resume", "info"
        ov_stage = 5
    elif eval_denom == 0 and total_runs > 0:
        posture_label, posture_tone = "Ready for SEC Accuracy Check", "info"
        ov_stage = 6
    else:
        posture_label, posture_tone = ("Database Connected", "success") if db_ok else ("Database Attention Needed", "warning")
        ov_stage = 7

    render_page_header(
        title=f"{PRODUCT_NAME} Overview",
        subtitle="Track live portfolio audit status, inspect saved checkpoints, or follow the guided SEC 10-K audit workflow.",
        status_label=posture_label,
        status_tone=posture_tone,
    )
    _render_stepper_from_summary(ov_stage, summary)
    render_flash_feedback()
    render_welcome_panel(allow_dismiss=True)
    render_guided_tour_panel("overview")

    # Guided Primary Next Action & Expected Result explaining current audit posture
    resumable_ready = [
        w for w in recoverable
        if w["status"] in ("INTERRUPTED", "RUNNING", "PENDING") or int(w.get("open_review_count", 0)) == 0
    ]
    if total_filings == 0:
        ov_status = "Your SQLite workspace is initialized cleanly with zero filings."
        ov_next = "Open Filing Analysis to select one or more supported companies and click 'Retrieve Latest 10-K Filings'."
        ov_expect = "FinovaLabs resolves official CIKs from SEC EDGAR, downloads the latest Form 10-K metadata, and saves deduplicated records in SQLite."
        next_label, next_target = "Start Audit in Filing Analysis →", "filing-analysis"
    elif total_runs == 0:
        ov_status = f"{total_filings} verified SEC Form 10-K filing(s) are stored and awaiting metric extraction."
        ov_next = "Open Filing Analysis, select a stored filing, and click 'Extract 8 Core Financial Metrics'."
        ov_expect = "Normalized USD/per-share figures, verbatim filing citations, 5-factor confidence scores, and Accounting/Segment/YoY validations appear in seconds."
        next_label, next_target = "Extract Metrics in Filing Analysis →", "filing-analysis"
    elif open_reviews > 0:
        ov_status = f"{open_reviews} escalated metric(s) are paused at checkpoint review and require an analyst decision."
        ov_next = "Open Human Review to compare the extracted figure side-by-side against filing evidence and click Approve, Correct Value, or Reject."
        ov_expect = "Your decision and SHA-256 audit record commit atomically, preserving the original value while unblocking checkpoint resume."
        next_label, next_target = f"Resolve {open_reviews} Escalation(s) →", "human-review"
    elif resumable_ready:
        ov_status = f"{len(resumable_ready)} saved workflow checkpoint(s) are cleared and ready to resume without repeating extraction."
        ov_next = "Click 'Resume Workflow' under Saved Workflows & Restart Recovery below (or inspect in Human Review)."
        ov_expect = "LangGraph continues from the saved checkpoint and completes the run without duplicating metrics or decisions."
        next_label, next_target = "Review Checkpoints in Human Review →", "human-review"
    elif eval_denom == 0:
        ov_status = f"All {total_runs} filing audit run(s) completed with zero open escalations."
        ov_next = "Open Accuracy Report and click 'Evaluate vs. SEC Facts' to benchmark your extracted values."
        ov_expect = "Separate Pre-Review and Post-Review accuracy rates, denominators, and Ground-Truth coverage charts plus CSV/JSON downloads."
        next_label, next_target = "Benchmark Accuracy vs. SEC →", "accuracy-report"
    else:
        ov_status = f"{total_runs} audit run(s) complete and {eval_denom} metric benchmark record(s) verified against SEC Company Facts."
        ov_next = "Open Audit Trail to verify sequential SHA-256 hash links and filter reviewer decisions, or audit another company."
        ov_expect = "Full chronological provenance (`Original` -> `Corrected`, timestamps, explanations) verified tamper-evident."
        next_label, next_target = "Inspect Audit Trail →", "audit-trail"

    with st.container(border=True):
        ac_left, ac_right = st.columns([3, 1.1])
        with ac_left:
            st.markdown(f"**Current Audit Posture:** {ov_status}")
            render_next_action_box(next_action=ov_next, expected_result=ov_expect)
        with ac_right:
            navigate_button(
                next_label,
                next_target,
                key="ov_primary_next_cta",
                primary=True,
                help_text="Jump directly to the recommended next workflow screen.",
            )
            render_field_tooltips_popover()

    if summary is not None:
        if eval_denom > 0:
            acc_value = f"{(pre_matches / eval_denom):.1%} / {(post_matches / eval_denom):.1%}"
            acc_detail = f"Pre ({pre_matches}/{eval_denom}) vs. Post ({post_matches}/{eval_denom}) SEC GT"
        else:
            acc_value = "—"
            acc_detail = "Run Accuracy Report benchmarks to measure"

        # Symmetrical 4-card KPI row (no orphaned 4+2 layout)
        render_metric_cards(
            [
                {
                    "label": "Companies & 10-Ks",
                    "value": f"{summary['total_companies']} / {summary['retrieved_filings']}",
                    "detail": f"{summary['total_runs']} audit run(s) ({summary['completed_runs']} done, {summary['paused_runs']} paused)",
                },
                {
                    "label": "Auto-Approved Metrics",
                    "value": f"{summary['auto_approved_metrics']} / {summary['extracted_metrics']}",
                    "detail": "Passed ≥90% confidence & financial rules",
                },
                {
                    "label": "Open Escalations",
                    "value": str(summary["open_reviews"]),
                    "detail": f"{summary['resolved_reviews']} resolved of {summary['total_escalations']} total",
                },
                {
                    "label": "SEC Accuracy (Pre / Post)",
                    "value": acc_value,
                    "detail": acc_detail,
                },
            ]
        )

    if recoverable:
        st.markdown('<div class="fl-section-title">Saved Workflows & Restart Recovery</div>', unsafe_allow_html=True)
        st.caption(
            "Checkpointed workflows remain durable in SQLite across application restarts and never re-run completed stages."
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
            headers=["Run ID", "Company / Accession", "Last Checkpoint", "Open Reviews", "Status"],
            rows=rec_rows,
            right_align_cols={3},
        )
        for w in recoverable:
            open_cnt = int(w.get("open_review_count", 0))
            if w["status"] in ("INTERRUPTED", "RUNNING", "PENDING") or open_cnt == 0:
                if st.button(
                    f"Resume Workflow {w['run_id']} ({w.get('current_stage') or humanize_status(w['status'])})",
                    key=f"overview_resume_{w['run_id']}",
                    type="primary",
                    help="Consequential action: resumes LangGraph execution from its saved SQLite checkpoint without duplicating completed stages.",
                ):
                    with st.spinner(f"Resuming checkpointed workflow {w['run_id']}..."):
                        outcome = safe_execute(
                            lambda rid=w["run_id"]: resume_audit_workflow(rid),
                            "workflow resume",
                        )
                    if outcome is not None:
                        flash_feedback(
                            "success",
                            f"Workflow `{outcome.run_id}` resumed cleanly from checkpoint -> `{humanize_status(outcome.status)}`.",
                        )
                        st.rerun()
            else:
                r_col1, r_col2 = st.columns([3, 1])
                with r_col1:
                    st.warning(
                        f"Run `{w['run_id']}` is paused with **{open_cnt}** open escalation(s). Resolve them before resuming."
                    )
                with r_col2:
                    navigate_button(
                        "Open Human Review →",
                        "human-review",
                        key=f"ov_jump_hr_{w['run_id']}",
                        primary=False,
                    )

    if runs:
        ov_c1, ov_c2 = st.columns([3, 2])
        with ov_c1:
            st.markdown('<div class="fl-section-title">Recent Filing Audit Runs</div>', unsafe_allow_html=True)
            rows = [
                [
                    f"{r.get('ticker') or r['cik']}",
                    r.get("accession_number") or r["run_id"],
                    r["form_type"],
                    r.get("current_stage") or "—",
                    _format_confidence(r.get("overall_confidence")),
                    (humanize_status(r["status"]), _status_tone_for_run(r["status"])),
                ]
                for r in runs
            ]
            render_status_table(
                headers=["Company", "Accession", "Form", "Stage", "Confidence", "Status"],
                rows=rows,
                right_align_cols={4},
            )
        with ov_c2:
            run_chart_rows = [
                {
                    "Run": f"{r.get('ticker') or r['cik']} ({r['run_id'][-4:]})",
                    "Confidence (%)": round((r.get("overall_confidence") or 0.0) * 100.0, 2),
                    "Status": humanize_status(r["status"]),
                }
                for r in reversed(runs[:10])
                if r.get("overall_confidence") is not None
            ]
            if run_chart_rows:
                st.markdown('<div class="fl-section-title">Confidence vs. 90% Cutoff</div>', unsafe_allow_html=True)
                run_df = pd.DataFrame(run_chart_rows)
                fig_runs = px.bar(
                    run_df,
                    x="Run",
                    y="Confidence (%)",
                    color="Status",
                    color_discrete_map={
                        "Completed": "#059669",
                        "Completed (With Rejections)": "#D97706",
                        "Paused for Review": "#2563EB",
                        "Interrupted": "#D97706",
                        "Running": "#1D4ED8",
                        "Failed": "#DC2626",
                    },
                )
                fig_runs.add_hline(
                    y=settings.confidence.auto_approve_threshold * 100.0,
                    line_dash="dash",
                    line_color="#0B1E36",
                    annotation_text=f"Cutoff ({settings.confidence.auto_approve_threshold:.0%})",
                )
                fig_runs.update_yaxes(range=[0, 108])
                render_plotly_chart(
                    fig_runs,
                    key="overview_run_conf_bar",
                    height=300,
                )
    else:
        render_empty_state(
            title="No filing audit runs recorded yet",
            description=(
                "FinovaLabs never fabricates financial numbers or run history. Real audit rows appear "
                "here as soon as you retrieve a 10-K and run extraction in Filing Analysis."
            ),
            badge_label="Empty State • Ready",
            next_step="Use 'Start Audit in Filing Analysis →' above to process your first company.",
        )

    if filings:
        with st.expander(f"Retrieved SEC 10-K Filings ({len(filings)})", expanded=False):
            filing_rows = [
                [
                    f.get("company_name") or "—",
                    f.get("ticker") or f["cik"],
                    f["form_type"],
                    f["filing_date"],
                    str(f["fiscal_year"]) if f.get("fiscal_year") else "—",
                    (humanize_status(f.get("retrieval_status") or "RETRIEVED"), "success"),
                ]
                for f in filings
            ]
            render_status_table(
                headers=["Company Name", "Ticker", "Form", "Filing Date", "Fiscal Year", "Status"],
                rows=filing_rows,
                right_align_cols={4},
            )

    with st.expander("System Configuration, Safe Restart & Reset Options", expanded=(not db_ok)):
        col_left, col_right = st.columns([3, 1])
        with col_left:
            if health is not None:
                size_kb = health["size_bytes"] / 1024
                render_info_card(
                    title="SQLite Persistence & Policy Thresholds",
                    body=(
                        f"Database: {health['db_path']} (SQLite {health['sqlite_version']}, {size_kb:.1f} KB). "
                        f"Logs: {settings.log_file}. Auto-approve ≥ {settings.confidence.auto_approve_threshold:.0%}, "
                        f"YoY alert ±{settings.validation.yoy_change_alert_threshold:.0%}."
                    ),
                    badge_label=f"{len(CORE_TABLES)}/{len(CORE_TABLES)} Tables Ready" if db_ok else "Schema Incomplete",
                    badge_tone="success" if db_ok else "danger",
                )
        with col_right:
            if st.button("Verify DB Health", type="primary", **stretch_width_kwargs(st.button)):
                with st.spinner("Checking SQLite schema integrity..."):
                    recheck = safe_execute(check_db_health, "live database health check")
                if recheck and recheck["healthy"]:
                    st.success(f"SQLite OK ({recheck['sqlite_version']})")
                elif recheck:
                    st.error(f"Missing tables: {', '.join(recheck['missing_tables'])}")

        st.markdown("---")
        sr_c1, sr_c2 = st.columns(2)
        with sr_c1:
            st.markdown("**Safe App Restart & UI Reset (Keeps All Real Data)**")
            st.caption(
                "Restarting the Streamlit server or refreshing your browser never deletes SQLite filings, "
                "metrics, human decisions, or the SHA-256 audit ledger. Use the button below to restore the "
                "Welcome panel, restart the guided tour, and clear UI filters safely."
            )
            if st.button(
                "Reset UI & Restart Welcome / Tour",
                key="ov_reset_ui_only",
                help="Non-destructive: resets only browser session state. Zero SQLite rows are altered.",
                **stretch_width_kwargs(st.button),
            ):
                reset_ui_session_state()
                flash_feedback(
                    "info",
                    "UI filters, welcome panel, and guided tour were reset safely. Real SQLite records remain intact.",
                )
                st.rerun()

        with sr_c2:
            st.markdown("**Clear Local Demo Database (Explicit Confirmation Required)**")
            st.caption(
                "Compliance data is never deleted automatically or via single click. Only use this if you "
                "explicitly want to wipe your local SQLite tables back to an empty genesis state."
            )
            wipe_cb = st.checkbox(
                "I confirm I want to permanently delete all local SQLite filings, metrics, review decisions, evaluations, and audit history.",
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
                        f"Confirmed local SQLite workspace reset removed {total_removed} record(s) across core tables.",
                    )
                    st.rerun()

    render_footer()


def render_filing_analysis_page() -> None:
    """Render the Filing Analysis page with guided retrieval, extraction, and inspection."""
    settings, summary = _bootstrap_page("Filing Analysis", active_step=2)
    if settings is None:
        render_footer()
        return

    runs = safe_execute(lambda: fetch_runs(limit=50), "audit runs query") or []
    filings = safe_execute(lambda: fetch_filing_metadata(limit=50), "SEC filing metadata query") or []
    supported = get_supported_company_options()

    fa_stage = 1 if not filings else (2 if not runs else 4)
    render_page_header(
        title="Filing Analysis",
        subtitle="Select supported public companies, retrieve official SEC Form 10-K filings, extract 8 core metrics, and inspect evidence and validations.",
        status_label=f"{len(filings)} Filing(s) Stored" if filings else "Step 1: Select Company",
        status_tone="success" if filings else "info",
    )
    _render_stepper_from_summary(fa_stage, summary)
    render_flash_feedback()
    render_guided_tour_panel("filing-analysis")

    if not filings:
        fa_next = "Pick one or more supported companies in Step 1 below and click 'Retrieve Latest 10-K Filings'."
        fa_expect = "FinovaLabs resolves official CIKs from SEC EDGAR, downloads Form 10-K metadata + Company Facts JSON, and unlocks Step 2."
    elif not runs:
        fa_next = "Choose your retrieved filing in Step 2 and click 'Extract 8 Core Financial Metrics'."
        fa_expect = "Extracts normalized USD & Diluted EPS figures with verbatim HTML citations, 5-factor confidence scores, and validation checks."
    else:
        fa_next = "Inspect the extracted metrics, confidence breakdown, and validations in Step 3 below, or click the recommended next-screen button."
        fa_expect = "Any low-confidence (<90%) or failed-validation metric pauses a SQLite checkpoint for Human Review; clean runs proceed straight to Accuracy Report."

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
    st.markdown('<div class="fl-section-title">Step 1 · Select Companies & Retrieve SEC 10-K</div>', unsafe_allow_html=True)
    option_map = {c.display_name: c.ticker for c in supported}
    all_labels = list(option_map.keys())
    if "fa_selected_labels" not in st.session_state:
        st.session_state["fa_selected_labels"] = all_labels[:2]

    def _sync_select_all() -> None:
        if st.session_state.get("fa_select_all_cb"):
            st.session_state["fa_selected_labels"] = list(all_labels)
        else:
            st.session_state["fa_selected_labels"] = all_labels[:1]

    with st.container(border=True):
        col_sel, col_opts, col_btn = st.columns([3, 1, 1.3])
        with col_sel:
            selected_labels = st.multiselect(
                "Supported companies (dynamic CIK lookup via SEC EDGAR)",
                options=all_labels,
                key="fa_selected_labels",
                help="Select one or more companies. CIKs are resolved dynamically from SEC company_tickers.json.",
            )
        with col_opts:
            st.checkbox(
                "Select all 5 companies",
                value=len(st.session_state["fa_selected_labels"]) == len(all_labels),
                key="fa_select_all_cb",
                on_change=_sync_select_all,
            )
            force_refresh = st.checkbox(
                "Force SEC refresh",
                value=False,
                help="Bypass local SEC disk cache and re-download JSON from data.sec.gov.",
            )
        with col_btn:
            st.write("")
            retrieve_clicked = st.button(
                "Retrieve Latest 10-K Filings",
                type="primary",
                disabled=not ua_ok,
                help="Fetches latest Form 10-K metadata and Company Facts from SEC EDGAR and saves deduplicated records to SQLite.",
                **stretch_width_kwargs(st.button),
            )

        with st.expander("SEC EDGAR Connection & Cache Policy", expanded=False):
            st.caption(
                f"User-Agent: `{ua_display}` • Rate Ceiling: `{settings.sec.max_requests_per_second} req/s` • "
                f"Timeout: `{settings.sec.request_timeout_seconds}s` • Cache: `{settings.cache_path}`"
            )

        if retrieve_clicked:
            if not selected_labels:
                st.warning("Select at least one company before retrieving filings.")
            else:
                selected_tickers = [option_map[lbl] for lbl in selected_labels]
                progress_bar = st.progress(0.0)
                with st.status("Connecting to SEC EDGAR...", expanded=True) as status_box:
                    def _on_progress(idx: int, total: int, ticker: str) -> None:
                        status_box.write(f"Resolving CIK and retrieving latest 10-K for **{ticker}** ({idx}/{total})...")
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
                            label=f"Retrieved {succeeded}/{len(outcomes)} latest 10-K filing(s) from SEC EDGAR.",
                            state="complete",
                            expanded=False,
                        )
                        flash_feedback(
                            "success",
                            f"Retrieved {succeeded}/{len(outcomes)} latest Form 10-K filing(s). Next: select a filing below and click 'Extract 8 Core Financial Metrics'.",
                        )
                        st.rerun()
                    else:
                        status_box.update(
                            label=f"Completed with {succeeded} retrieved and {failed} failed.",
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
        with st.expander(f"Stored 10-K Filings in SQLite ({len(filings)})", expanded=False):
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
                headers=["Company", "Ticker", "CIK", "Form", "Filing Date", "FY", "Accession #", "Status"],
                rows=filing_rows,
                right_align_cols={5},
            )

    # Step 2: Select Filing & Start Processing
    st.markdown('<div class="fl-section-title">Step 2 · Run Audited 8-Metric Extraction & Validation</div>', unsafe_allow_html=True)
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
                "Select a retrieved 10-K filing to audit or inspect",
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
            title=f"{selected_filing_row.get('company_name') or selected_filing_row['cik']} ({selected_filing_row.get('ticker') or '—'}) — {selected_filing_row['form_type']}",
            body=(
                f"CIK: {selected_filing_row['cik']} • Accession: {selected_filing_row['accession_number']} • "
                f"Filed: {selected_filing_row['filing_date']} • Period End: {selected_filing_row.get('reporting_period') or '—'} • "
                f"Fiscal Year: {selected_filing_row.get('fiscal_year') or '—'}"
            ),
            badge_label=humanize_status(latest_run["status"]) if latest_run else "Ready to Extract",
            badge_tone=_status_tone_for_run(latest_run["status"]) if latest_run else "info",
        )

        act_c1, act_c2, act_c3 = st.columns([2.2, 1.5, 1.3])
        with act_c1:
            include_html = st.checkbox(
                "Cross-check 10-K HTML Inline XBRL (scale & table evidence)",
                value=True,
                help=f"{TOOLTIP_EVIDENCE} Also enables: {TOOLTIP_UNIT}",
            )
        with act_c2:
            force_new_run = False
            if latest_run is not None:
                force_new_run = st.checkbox(
                    "Confirm fresh re-audit",
                    value=False,
                    help=f"By default FinovaLabs idempotently reuses the existing saved run. {TOOLTIP_CHECKPOINT}",
                    key=f"fa_confirm_rerun_{selected_accn}",
                )
        with act_c3:
            extract_label = "Re-Run Audit Workflow" if force_new_run else "Extract 8 Core Financial Metrics"
            run_clicked = st.button(
                extract_label,
                type="primary",
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

            with st.status("Running audited extraction, confidence scoring & financial validations...", expanded=True) as ext_status:
                wf_outcome = safe_execute(_run_workflow, "audited workflow execution")
                if wf_outcome is not None:
                    st.session_state["fl_active_run_id"] = wf_outcome.run_id
                    if wf_outcome.paused:
                        ext_status.update(
                            label=(
                                f"Workflow {wf_outcome.run_id} PAUSED: "
                                f"{len(wf_outcome.auto_approved_metrics)} auto-approved, "
                                f"{wf_outcome.open_task_count} escalated for Human Review."
                            ),
                            state="complete",
                            expanded=False,
                        )
                        flash_feedback(
                            "warning",
                            f"Run `{wf_outcome.run_id}` paused at checkpoint with {wf_outcome.open_task_count} escalated task(s). Open Human Review to resolve.",
                        )
                    else:
                        msg_prefix = "Reused saved run" if getattr(wf_outcome, "reused_existing_run", False) else "Completed run"
                        ext_status.update(
                            label=f"{msg_prefix} {wf_outcome.run_id}: {len(wf_outcome.auto_approved_metrics)} metric(s) auto-approved.",
                            state="complete",
                            expanded=False,
                        )
                        flash_feedback(
                            "success",
                            f"{msg_prefix} `{wf_outcome.run_id}` ({humanize_status(wf_outcome.status)}): {len(wf_outcome.auto_approved_metrics)} auto-approved.",
                        )
                    st.rerun()
                else:
                    ext_status.update(label="Audited workflow execution failed.", state="error", expanded=True)

        # Next-action CTA banner specific to this filing's live workflow posture
        if latest_run is not None:
            if latest_run["status"] == "PAUSED_FOR_REVIEW":
                n1, n2 = st.columns([3, 1])
                with n1:
                    st.warning(
                        f"**Action Needed:** Run `{latest_run['run_id']}` is paused at its LangGraph SQLite checkpoint awaiting Human Review."
                    )
                with n2:
                    navigate_button(
                        "Resolve in Human Review →",
                        "human-review",
                        key=f"fa_next_hr_{selected_accn}",
                        primary=True,
                    )
            elif latest_run["status"] in ("COMPLETED", "COMPLETED_WITH_REJECTIONS"):
                n1, n2 = st.columns([3, 1])
                with n1:
                    st.success(
                        f"**Audit Complete ({humanize_status(latest_run['status'])}):** Ready to benchmark against SEC Company Facts."
                    )
                with n2:
                    navigate_button(
                        "Benchmark in Accuracy Report →",
                        "accuracy-report",
                        key=f"fa_next_acc_{selected_accn}",
                        primary=True,
                    )
    else:
        render_empty_state(
            title="Retrieve a 10-K filing in Step 1 first",
            description=(
                "No saved Form 10-K filings exist in SQLite yet. Select a company above and click "
                "'Retrieve Latest 10-K Filings' to unlock metric extraction."
            ),
            badge_label="Awaiting Retrieval",
            next_step="Step 2 unlocks automatically once SEC EDGAR metadata is saved.",
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

    # Step 3: Inspect Extracted Metrics, Confidence, Evidence & Validations
    st.markdown('<div class="fl-section-title">Step 3 · Inspect Extracted Metrics, Evidence & Validations</div>', unsafe_allow_html=True)
    tab_metrics, tab_vals, tab_spec = st.tabs(
        [
            f"Extracted Metrics ({len(metrics or [])})",
            f"Validation Checks ({len(validations or [])})",
            "Approved 8-Metric Spec & Scoring Method",
        ]
    )

    with tab_metrics:
        if metrics:
            extracted_cnt = sum(1 for m in metrics if m.get("extraction_status") == "EXTRACTED")
            auto_cnt = sum(1 for m in metrics if m.get("review_status") == "AUTO_APPROVED")
            esc_cnt = sum(1 for m in metrics if m.get("review_status") == "REVIEW_REQUIRED")
            render_metric_cards(
                [
                    {"label": "Extracted", "value": f"{extracted_cnt} / {len(metrics)}", "detail": "Non-missing metrics"},
                    {"label": "Auto-Approved", "value": str(auto_cnt), "detail": "Met confidence + validations"},
                    {"label": "Escalated", "value": str(esc_cnt), "detail": "Sent to Human Review"},
                    {
                        "label": "Avg Confidence",
                        "value": _format_confidence(sum(float(m.get("confidence_score") or 0.0) for m in metrics) / len(metrics)),
                        "detail": f"Cutoff ≥ {settings.confidence.auto_approve_threshold:.0%}",
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
                headers=["Metric", "Normalized Value", "Unit & Scale", "Period", "Confidence", "Validation", "Governance"],
                rows=rows,
                right_align_cols={1, 4},
            )

            conf_rows = [
                {
                    "Metric": m["metric_name"],
                    "Confidence (%)": round((m.get("confidence_score") or 0.0) * 100.0, 2),
                    "Governance": humanize_status(m.get("review_status") or "NOT_REQUIRED"),
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
                    color="Governance",
                    color_discrete_map={
                        "Auto-Approved": "#059669",
                        "Approved": "#1D4ED8",
                        "Corrected": "#2563EB",
                        "Needs Review": "#D97706",
                        "Rejected": "#DC2626",
                        "Not Required": "#64748B",
                    },
                )
                fig_conf.add_vline(
                    x=settings.confidence.auto_approve_threshold * 100.0,
                    line_dash="dash",
                    line_color="#0B1E36",
                    annotation_text=f"Cutoff ({settings.confidence.auto_approve_threshold:.0%})",
                )
                fig_conf.update_xaxes(range=[0, 108])
                render_plotly_chart(
                    fig_conf,
                    title="Confidence Score vs. Approval Threshold",
                    key=f"fa_conf_chart_{selected_accn or 'all'}",
                    height=310,
                )

            with st.expander("Source Evidence Snippets & 5-Factor Confidence Breakdown", expanded=False):
                for m in metrics:
                    conf_pct = _format_confidence(m.get("confidence_score"))
                    st.markdown(
                        f"**{m['metric_name']}** — {humanize_status(m.get('extraction_status'))} | "
                        f"Concept: `us-gaap:{m.get('xbrl_concept') or 'None'}` | "
                        f"Raw: `{m.get('raw_value') or '—'}` | Confidence: **{conf_pct}**"
                    )
                    st.markdown(
                        f"<div class='fl-evidence-box'><strong>Location:</strong> {m.get('evidence_location') or '—'}<br>"
                        f"<strong>Evidence:</strong> {m.get('source_evidence') or 'No verbatim snippet captured.'}<br>"
                        f"<strong>Source:</strong> {m.get('source_url') or '—'}</div>",
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
                                    headers=["Factor", "Weight", "Raw", "Weighted", "Status", "Rationale"],
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
                                st.caption(f"Candidate facts recorded ({len(cands)}):")
                                for c in cands[:5]:
                                    st.code(
                                        f"us-gaap:{c.get('concept')} | val={c.get('normalized_value')} {c.get('reported_unit')} "
                                        f"| raw={c.get('raw_value')} (scale={c.get('scale_factor')}x) | {c.get('evidence_location')}",
                                        language="text",
                                    )
                        except ValueError:
                            pass
        else:
            render_empty_state(
                title="No extracted metrics for this filing yet",
                description="FinovaLabs never invents placeholder metrics. Click 'Extract 8 Core Financial Metrics' in Step 2 to process this filing.",
                badge_label="Awaiting Extraction",
                next_step="Extracted numbers, units, periods, evidence snippets, and 5-factor scores will appear here.",
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
                headers=["Rule", "Scope / Metric", "Status", "Variance %", "Explanation"],
                rows=val_rows,
                right_align_cols={3},
            )
            with st.expander("Validation Input References & Tolerances", expanded=False):
                for v in validations:
                    st.markdown(
                        f"**{v['rule_name']} — {v['metric_name']}** (`{v['status']}`) • "
                        f"Tolerance: `{v.get('tolerance_used') or '—'}` • Escalated: `{bool(v.get('escalated'))}`"
                    )
                    if v.get("input_metric_refs_json"):
                        st.code(v["input_metric_refs_json"], language="json")
        else:
            render_empty_state(
                title="No financial validation checks run yet",
                description="Extract metrics for the selected filing in Step 2 to evaluate the accounting equation, segment reconciliation, and YoY checks.",
                badge_label="No Validations",
                next_step="Outputs cleanly distinguish Pass, Warning, Fail, and Not Applicable.",
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
                ("Mapped", "success"),
            ]
            for spec in approved_specs
        ]
        render_status_table(
            headers=["Metric", "Period Type", "Unit", "Sign Convention", "Primary US-GAAP Concepts", "Status"],
            rows=spec_rows,
        )
        st.caption(
            f"Active Confidence Engine v{settings.confidence.scoring_version} • "
            f"Threshold: ≥ {settings.confidence.auto_approve_threshold:.0%}"
        )
        st.code(SCORING_METHOD_DOC, language="text")

    render_footer()


def render_human_review_page() -> None:
    """Render the Human Review queue backed by SQLite review_tasks."""
    settings, summary = _bootstrap_page("Human Review", active_step=3)
    if settings is None:
        render_footer()
        return

    all_tasks = safe_execute(lambda: fetch_review_tasks(limit=100), "review tasks query") or []
    open_tasks = [t for t in all_tasks if t["status"] == "OPEN"]
    open_count = len(open_tasks)
    resolved_count = len(all_tasks) - open_count

    render_page_header(
        title="Human Review",
        subtitle="Inspect escalated metrics side-by-side with source evidence, record justified approve/correct/reject decisions, and resume paused workflows.",
        status_label=f"{open_count} Pending Review(s)" if open_count else "Queue Clear",
        status_tone="warning" if open_count else "success",
    )
    _render_stepper_from_summary(5, summary)
    render_flash_feedback()
    render_guided_tour_panel("human-review")

    if open_count > 0:
        hr_next = f"Expand Pending Task #1 below, verify the extracted figure against its 10-K citation, and click Approve, Correct Value, or Reject."
        hr_expect = "SQLite commits your justification, session ID, and SHA-256 audit event atomically while preserving the original figure, then resumes unblocked checkpoints."
    else:
        hr_next = "No pending escalations remain. Click 'Continue to Accuracy Report ->' or inspect resolved history / append-only amendments below."
        hr_expect = "Accuracy Report compares your pre-review raw values vs. final post-review decisions against official SEC Company Facts."

    hr_g1, hr_g2 = st.columns([3.4, 1.0])
    with hr_g1:
        render_next_action_box(next_action=hr_next, expected_result=hr_expect)
    with hr_g2:
        render_field_tooltips_popover()

    conf = settings.confidence
    val = settings.validation
    render_metric_cards(
        [
            {"label": "Pending Escalations", "value": str(open_count), "detail": "Shown first below for analyst action"},
            {"label": "Resolved Decisions", "value": str(resolved_count), "detail": "Committed permanently to SQLite"},
            {"label": "Auto-Approve Cutoff", "value": f"≥ {conf.auto_approve_threshold:.0%}", "detail": "Plus mandatory validation pass"},
            {"label": "YoY Alert Threshold", "value": f"±{val.yoy_change_alert_threshold:.0%}", "detail": f"Segment tolerance ±{val.segment_reconciliation_tolerance:.1%}"},
        ]
    )

    recoverable_runs = safe_execute(lambda: fetch_recoverable_workflows(limit=50), "recoverable workflow check") or []
    resumable_runs = [
        r for r in recoverable_runs
        if r["status"] in ("INTERRUPTED", "RUNNING", "PENDING")
        or (r["status"] == "PAUSED_FOR_REVIEW" and int(r.get("open_review_count", 0)) == 0)
    ]

    if open_count == 0 and not resumable_runs:
        n1, n2 = st.columns([3, 1])
        with n1:
            if all_tasks:
                st.success("**All escalations resolved:** Every pending human review task has a committed decision.")
            else:
                st.info("**Review queue is empty:** No pending escalations require action right now.")
        with n2:
            if (summary or {}).get("total_runs", 0) > 0:
                navigate_button("Continue to Accuracy Report →", "accuracy-report", key="hr_next_acc", primary=True)
            else:
                navigate_button("Start Audit in Filing Analysis →", "filing-analysis", key="hr_next_fa", primary=True)

    status_filter = st.selectbox(
        "Filter Review View by Status",
        ["ALL", "OPEN", "APPROVED", "CORRECTED", "REJECTED"],
        help="Filters pending escalation cards and the review history table together.",
    )
    filtered = (
        all_tasks
        if status_filter == "ALL"
        else [t for t in all_tasks if t["status"] == status_filter]
    )

    # Pending items always shown FIRST when filter permits
    if status_filter in {"ALL", "OPEN"}:
        if open_tasks:
            st.markdown('<div class="fl-section-title">Pending Escalations (Action Required)</div>', unsafe_allow_html=True)
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
                    f"{t.get('period_start') or 'Instant'} → {t.get('period_end') or '—'}"
                )
                header = (
                    f"[PENDING #{idx + 1}] {company_display} • {t.get('metric_name') or '—'} • "
                    f"Extracted: {orig_display} • Confidence: {_format_confidence(t.get('confidence_score'))}"
                )
                with st.expander(header, expanded=(idx == 0)):
                    st.warning(f"**Why Review Is Required:** {t['reason']}")
                    col_evidence, col_decision = st.columns([1.15, 1.0])

                    with col_evidence:
                        st.markdown("**Extracted Figure & Filing Evidence**")
                        st.markdown(
                            f"**Company:** {company_display}  \n"
                            f"**Metric:** {t.get('metric_name') or '—'}  \n"
                            f"**Original Extracted Value:** `{orig_display}` (raw: `{t.get('raw_value') or '—'}`)  \n"
                            f"**<abbr class='fl-tip' title='{TOOLTIP_PERIOD}'>Period</abbr>:** `{period_display}` | "
                            f"**<abbr class='fl-tip' title='{TOOLTIP_UNIT}'>Unit</abbr>:** `{unit_label} ({currency_label})`  \n"
                            f"**<abbr class='fl-tip' title='{TOOLTIP_CONFIDENCE}'>Confidence</abbr>:** `{_format_confidence(t.get('confidence_score'))}` "
                            f"(Threshold `{_format_confidence(t.get('confidence_threshold'))}`) | "
                            f"**<abbr class='fl-tip' title='{TOOLTIP_VALIDATION}'>Validation</abbr>:** `{humanize_status(t.get('validation_status') or 'PENDING')}`  \n"
                            f"**Source Filing:** `{t.get('form_type') or '10-K'}` `{t.get('accession_number') or '—'}` "
                            f"(Filed `{t.get('filing_date') or '—'}`)  \n"
                            f"**Source URL:** {t.get('source_url') or '—'}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"<div class='fl-evidence-box'><strong><abbr class='fl-tip' title='{TOOLTIP_EVIDENCE}'>Citation</abbr> ({t.get('evidence_location') or 'No HTML location'}):</strong><br>"
                            f"{t.get('source_evidence') or 'No verbatim filing snippet captured for this metric.'}</div>",
                            unsafe_allow_html=True,
                        )

                    with col_decision:
                        st.markdown("**Analyst Decision & Audit Justification**")
                        default_corr = (
                            str(t["normalized_decimal"])
                            if t.get("normalized_decimal") is not None
                            else (str(t["normalized_value"]) if t.get("normalized_value") is not None else "")
                        )
                        corr_input = st.text_input(
                            "Corrected Value (used only when clicking 'Correct Value')",
                            value=default_corr,
                            key=f"corr_{t['task_id']}",
                            help="Enter the normalized numeric value in the reported unit. Original extracted value stays preserved permanently.",
                        )
                        if default_corr and corr_input.strip() and corr_input.strip() != default_corr:
                            st.caption(f"Proposed change preview: `{default_corr}` -> `{corr_input.strip()}` ({unit_label})")
                        reviewer_input = st.text_input(
                            "Reviewer Identifier",
                            value="analyst",
                            key=f"rev_{t['task_id']}",
                            help="Recorded alongside your browser session ID in the append-only SHA-256 audit ledger.",
                        )
                        note_input = st.text_area(
                            "Explanation / Audit Justification (required for Correct Value & Reject)",
                            placeholder="State how you verified this figure against the 10-K statement or why you are rejecting it...",
                            key=f"note_{t['task_id']}",
                        )
                        st.caption(
                            "Consequential action: submitting commits your decision and SHA-256 audit event atomically before resuming the workflow."
                        )

                        act_clicked: str | None = None
                        b1, b2, b3 = st.columns(3)
                        with b1:
                            if st.button(
                                "Approve",
                                key=f"btn_approve_{t['task_id']}",
                                type="primary",
                                help="Accept original extracted value as audited.",
                                **stretch_width_kwargs(st.button),
                            ):
                                act_clicked = "APPROVE"
                        with b2:
                            if st.button(
                                "Correct Value",
                                key=f"btn_correct_{t['task_id']}",
                                help="Save the corrected numeric value above (requires explanation).",
                                **stretch_width_kwargs(st.button),
                            ):
                                act_clicked = "EDIT"
                        with b3:
                            if st.button(
                                "Reject",
                                key=f"btn_reject_{t['task_id']}",
                                help="Reject unusable/unverified metric (requires explanation).",
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
                                        f"Task `{t['task_id']}` was already resolved as `{humanize_status(latest_state[0]['status'])}` — duplicate submission prevented.",
                                    )
                                    st.rerun()

                                with st.spinner("Committing decision to SQLite & resuming workflow..."):
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
                                        f"Decision saved (`{humanize_status(res['decision']['status'])}`). Workflow `{wf_out['run_id']}` resumed -> `{humanize_status(wf_out['status'])}`. Next: open Accuracy Report to benchmark vs. SEC Facts.",
                                    )
                                else:
                                    flash_feedback(
                                        "success",
                                        f"Decision saved (`{humanize_status(res['decision']['status'])}`). {res['remaining_open_for_run']} open task(s) remain in run.",
                                    )
                                st.rerun()
                            except Exception as exc:
                                render_error_banner(
                                    "Review decision could not be recorded",
                                    str(exc),
                                    hint="Enter an explanation for Correct Value / Reject and a valid numeric figure if editing.",
                                )
        elif all_tasks and status_filter == "OPEN":
            render_empty_state(
                title="No pending review tasks remain",
                description="All escalated items in SQLite have already been approved, corrected, or rejected.",
                badge_label="Queue Clear",
                next_step="Switch the filter to ALL to inspect completed review decisions or proceed to Accuracy Report.",
            )

    if resumable_runs:
        st.warning(f"**Ready to Resume ({len(resumable_runs)}):** Saved workflow checkpoint(s) have zero remaining open tasks.")
        for r in resumable_runs:
            if st.button(
                f"Resume Workflow {r['run_id']} ({humanize_status(r['status'])} @ {r.get('current_stage') or '—'})",
                key=f"resume_{r['run_id']}",
                type="primary",
            ):
                with st.spinner(f"Resuming checkpointed workflow {r['run_id']}..."):
                    outcome = safe_execute(lambda rid=r["run_id"]: resume_audit_workflow(rid), "workflow resume")
                if outcome is not None:
                    flash_feedback(
                        "success",
                        f"Workflow `{outcome.run_id}` resumed -> `{humanize_status(outcome.status)}`.",
                    )
                    st.rerun()

    all_metrics = safe_execute(lambda: fetch_extracted_metrics(limit=200), "amendable metrics query") or []
    amendable_metrics = [m for m in all_metrics if m.get("review_status") != "REVIEW_REQUIRED"]
    if amendable_metrics:
        with st.expander("Submit Subsequent Correction (Append-Only Audit Amendment)", expanded=False):
            st.caption(
                "Appends a new audit record and updated reviewed value to an already-approved or auto-approved metric. "
                "Previous audit records and the original extracted value are never overwritten."
            )
            metric_options = {
                m["id"]: (
                    f"{m.get('ticker') or m.get('cik')} • {m['metric_name']} "
                    f"({m.get('accession_number') or '—'}) — {humanize_status(m.get('review_status'))}"
                )
                for m in amendable_metrics
            }
            sel_amend_id = st.selectbox(
                "Select Metric to Amend",
                options=list(metric_options.keys()),
                format_func=lambda mid: metric_options.get(mid, str(mid)),
                key="hr_amend_metric_id",
            )
            sel_m = next(m for m in amendable_metrics if m["id"] == sel_amend_id)
            m_unit = sel_m.get("unit") or "USD"
            orig_m_disp = _format_decimal_metric(sel_m.get("normalized_decimal"), sel_m.get("normalized_value"), m_unit)
            curr_m_disp = _format_decimal_metric(sel_m.get("reviewed_decimal"), sel_m.get("reviewed_value"), m_unit)
            st.markdown(
                f"**Permanent Original Value:** `{orig_m_disp}` | "
                f"**Current Reviewed Value:** `{curr_m_disp}` | "
                f"**Workflow Run:** `{sel_m.get('run_id') or 'Standalone'}`"
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
                amend_reviewer = st.text_input("Reviewer ID", value="analyst", key="hr_amend_reviewer")
            amend_note = st.text_area(
                "Amendment Explanation (required for EDIT / REJECT)",
                placeholder="Explain the reason for this subsequent audit amendment...",
                key="hr_amend_note",
            )
            if st.button("Record Append-Only Amendment", key="btn_record_amendment", type="primary"):
                try:
                    with st.spinner("Appending audit amendment to SQLite..."):
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
                        f"(`{humanize_status(amend_res['decision']['status'])}`). Earlier history preserved untouched.",
                    )
                    st.rerun()
                except Exception as exc:
                    render_error_banner("Amendment could not be recorded", str(exc))

    st.markdown('<div class="fl-section-title">Review Queue History</div>', unsafe_allow_html=True)
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
            headers=["Company / Filing", "Metric", "Original Value", "Reviewed Value", "Confidence", "Escalation Reason", "Status"],
            rows=rows,
            right_align_cols={2, 3, 4},
        )
    else:
        render_empty_state(
            title="No review tasks match the selected status filter",
            description="Metrics flagged by low confidence (<90%) or failed financial validation rules appear here for review.",
            badge_label="Queue Clear",
            next_step="Run an audit in Filing Analysis or set the filter above to ALL.",
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
    """Render the Accuracy Report page for SEC Company Facts benchmarking and exports."""
    settings, posture_summary = _bootstrap_page("Accuracy Report", active_step=4)
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
        title="Accuracy Report",
        subtitle=(
            "Compare raw automated extraction and final human-reviewed figures against "
            "official SEC Company Facts XBRL entries with strict matching rules."
        ),
        status_label=f"{len(all_evaluations)} Benchmarked" if all_evaluations else "Awaiting Benchmark",
        status_tone="success" if all_evaluations else "neutral",
    )
    _render_stepper_from_summary(6, posture_summary)
    render_flash_feedback()
    render_guided_tour_panel("accuracy-report")

    if not all_runs:
        acc_next = "Click 'Start Audit in Filing Analysis ->' to retrieve a Form 10-K and run metric extraction first."
        acc_expect = "Once at least one workflow run exists, you can benchmark every metric against official SEC Company Facts XBRL entries."
    elif not all_evaluations:
        acc_next = "Select an audit run below (or 'All Audit Runs') and click 'Evaluate vs. SEC Facts'."
        acc_expect = "FinovaLabs checks exact company CIK, US-GAAP tag, FY annual period, and unit compatibility, showing Pre-Review vs. Post-Review accuracy."
    else:
        acc_next = "Review the Pre vs. Post accuracy charts and breakdown tables below, export CSV/JSON if needed, or inspect the Audit Trail."
        acc_expect = "Verifies whether human corrections closed extraction gaps without hiding raw automated error rates."

    acc_g1, acc_g2 = st.columns([3.4, 1.0])
    with acc_g1:
        render_next_action_box(next_action=acc_next, expected_result=acc_expect)
    with acc_g2:
        render_field_tooltips_popover()

    if not all_runs:
        render_info_card(
            title="Primary Next Action: Run a Filing Audit First",
            body=(
                "No audit runs exist in SQLite yet. Retrieve a 10-K filing and extract metrics in "
                "Filing Analysis before benchmarking against SEC Company Facts."
            ),
            badge_label="Step 1 Required",
            badge_tone="info",
        )
        navigate_button(
            "Start Audit in Filing Analysis ->",
            "filing-analysis",
            key="acc_go_fa_empty",
            primary=True,
        )
    else:
        with st.container(border=True):
            st.markdown("**1. Benchmark Extracted Runs Against SEC Company Facts**")
            st.caption(
                "Matches each extracted metric strictly by company CIK, US-GAAP concept, annual FY period, and unit. "
                "Pre-review and post-review accuracy are calculated separately."
            )
            run_labels = {
                r["run_id"]: f"{r.get('ticker') or r['cik']} • {r.get('accession_number') or r['run_id']} ({humanize_status(r['status'])})"
                for r in all_runs
            }
            existing_eval_runs = {e["run_id"] for e in all_evaluations}
            c1, c2, c3 = st.columns([3, 1.2, 1.4])
            with c1:
                eval_target = st.selectbox(
                    "Audit run to benchmark",
                    options=["ALL_RUNS", *run_labels.keys()],
                    format_func=lambda k: "All Audit Runs" if k == "ALL_RUNS" else run_labels.get(k, k),
                    key="acc_eval_target",
                    help="Select one workflow run or benchmark every recorded run in SQLite.",
                )
            with c2:
                force_refresh_cf = st.checkbox(
                    "Force SEC refresh",
                    value=False,
                    key="acc_force_refresh",
                    help="Bypass the cached Company Facts JSON and query live SEC EDGAR APIs.",
                )
            with c3:
                run_eval_clicked = st.button(
                    "Evaluate vs. SEC Facts",
                    type="primary",
                    **stretch_width_kwargs(st.button),
                )

            target_will_overwrite = (
                bool(existing_eval_runs)
                if eval_target == "ALL_RUNS"
                else eval_target in existing_eval_runs
            )
            if target_will_overwrite:
                st.caption(
                    "Re-evaluating overwrites stored Company Facts comparison snapshots for matching run(s) "
                    "while preserving your human review decisions and append-only audit trail."
                )

            if run_eval_clicked:
                target_ids = list(run_labels.keys()) if eval_target == "ALL_RUNS" else [eval_target]
                ok_count = 0
                with st.spinner("Comparing extracted metrics against SEC Company Facts..."):
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
                        f"Evaluated {ok_count} audit run(s) against SEC Company Facts and saved results to SQLite.",
                    )
                    st.rerun()
                else:
                    render_error_banner(
                        "SEC Company Facts evaluation failed",
                        "No selected audit runs could be evaluated. Check connectivity or SEC User-Agent settings.",
                    )

    # Company & run filters
    company_opts = sorted({(e.get("ticker") or e.get("cik") or "UNKNOWN") for e in all_evaluations})
    run_opts = sorted({e["run_id"] for e in all_evaluations})
    if all_evaluations:
        f1, f2 = st.columns(2)
        with f1:
            sel_company = st.selectbox("Filter by Company", ["ALL", *company_opts], key="acc_filter_company")
        with f2:
            sel_run = st.selectbox("Filter by Run ID", ["ALL", *run_opts], key="acc_filter_run")
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
                "label": "Pre-Review Raw Accuracy",
                "value": pre_acc_display,
                "detail": summary.pre_denominator_label if summary.total_records else "No records yet",
            },
            {
                "label": "Post-Review Accuracy",
                "value": post_acc_display,
                "detail": (
                    f"{summary.post_denominator_label} • +{summary.human_corrected_matches} human-fixed"
                    if summary.total_records
                    else "Human corrections tracked separately"
                ),
            },
            {
                "label": "SEC Ground-Truth Coverage",
                "value": gt_cov_display,
                "detail": summary.coverage_denominator_label if summary.total_records else "Awaiting evaluations",
            },
            {
                "label": "Mismatches & Unverified",
                "value": str(non_match_total),
                "detail": (
                    f"Mismatch: {summary.pre_mismatches} | Unmatched: {summary.unmatched_record_count} | "
                    f"No GT: {summary.unavailable_reference_count}"
                ),
            },
        ]
    )

    if evaluations:
        act_c1, act_c2, _ = st.columns([1.4, 1.4, 2])
        with act_c1:
            navigate_button(
                "Inspect Audit Trail ->",
                "audit-trail",
                key="acc_go_audit",
                primary=True,
                help_text="Review the tamper-evident append-only decision ledger for these runs.",
            )
        with act_c2:
            navigate_button(
                "Open Human Review",
                "human-review",
                key="acc_go_hr",
                primary=False,
                help_text="Resolve open escalations or submit append-only corrections.",
            )

        with st.expander("Matching Rules, Denominators & Ground-Truth Coverage Explained", expanded=True):
            st.markdown(
                f"- **Reference Source & Matching Rules:** Each extracted metric is matched against the official "
                f"SEC EDGAR Company Facts JSON on exact **company CIK**, **US-GAAP XBRL concept**, **annual (`FY`) fiscal period**, "
                f"and **compatible unit**. Period mismatches (`{summary.period_mismatch_count}`), unit mismatches "
                f"(`{summary.unit_mismatch_count}`), and missing ground-truth facts (`{summary.unavailable_reference_count}`) "
                f"**never count as matches**.\n"
                f"- **Pre-Review Raw Accuracy (`{pre_acc_display}`):** Evaluates automated extraction before human edits "
                f"(`{summary.pre_denominator_label}`, overall conservative rate across all extracted + unmatched records: "
                f"`{summary.pre_review_accuracy_overall:.1%}`).\n"
                f"- **Post-Review Accuracy (`{post_acc_display}`):** Evaluates final reviewed values after human approval or edits "
                f"(`{summary.post_denominator_label}`, overall rate: `{summary.post_review_accuracy_overall:.1%}`).\n"
                f"- **Coverage (`{gt_cov_display}`):** Share of records with a verifiable SEC Company Facts reference "
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
                            "Pre-Review Accuracy (%)": round((c.pre_review_accuracy_evaluable or 0.0) * 100.0, 2),
                            "Post-Review Accuracy (%)": round((c.post_review_accuracy_evaluable or 0.0) * 100.0, 2),
                            "GT Coverage (%)": round(c.ground_truth_coverage * 100.0, 2),
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
                        "Pre-Review Accuracy (%)": "#1D4ED8",
                        "Post-Review Accuracy (%)": "#059669",
                        "GT Coverage (%)": "#64748B",
                    },
                )
                fig_comp.update_yaxes(range=[0, 108])
                render_plotly_chart(
                    fig_comp,
                    title="Company-Level Pre vs. Post Accuracy & GT Coverage (%)",
                    key="acc_company_plotly",
                )

        with chart_col2:
            if summary.by_metric:
                met_df = pd.DataFrame(
                    [
                        {
                            "Metric": m.group_label,
                            "Pre-Review Accuracy (%)": round((m.pre_review_accuracy_evaluable or 0.0) * 100.0, 2),
                            "Post-Review Accuracy (%)": round((m.post_review_accuracy_evaluable or 0.0) * 100.0, 2),
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
                        "Pre-Review Accuracy (%)": "#1D4ED8",
                        "Post-Review Accuracy (%)": "#059669",
                    },
                )
                fig_met.update_xaxes(range=[0, 108])
                fig_met.update_yaxes(categoryorder="total ascending", title=None)
                render_plotly_chart(
                    fig_met,
                    title="Metric-Level Pre-Review vs. Post-Review Accuracy (%)",
                    key="acc_metric_plotly",
                )

        st.markdown('<div class="fl-section-title">Company-Level Accuracy Breakdown</div>', unsafe_allow_html=True)
        render_status_table(
            headers=[
                "Company",
                "Total",
                "Verifiable GT",
                "GT Coverage",
                "Pre-Review (Denom)",
                "Pre Acc",
                "Post-Review (Denom)",
                "Post Acc",
                "Human Fixed",
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
        )

        st.markdown('<div class="fl-section-title">Metric-Level Accuracy Breakdown</div>', unsafe_allow_html=True)
        render_status_table(
            headers=[
                "Metric",
                "Total",
                "Verifiable GT",
                "GT Coverage",
                "Pre-Review (Denom)",
                "Pre Acc",
                "Post-Review (Denom)",
                "Post Acc",
                "Human Fixed",
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
        )

        st.markdown('<div class="fl-section-title">SEC Company Facts Comparison & Reference Provenance</div>', unsafe_allow_html=True)
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
                "Concept",
                "Period",
                "Unit",
                "Pre-Review",
                "Post-Review",
                "SEC Ground Truth",
                "Pre Abs Diff",
                "Pre % Diff",
                "Pre Status",
                "Post Status",
            ],
            rows=detail_rows,
            right_align_cols={5, 6, 7, 8, 9},
        )

        with st.expander("Reference Provenance & Explanations", expanded=False):
            for e in evaluations:
                st.markdown(
                    f"**{e.get('ticker') or e.get('cik')} • {e['metric_name']} (`{e['run_id']}`)** — "
                    f"Source: `{e.get('reference_source_url') or 'N/A'}`  \n"
                    f"{e.get('explanation') or ''}"
                )

        st.markdown('<div class="fl-section-title">Export Branded FinovaLabs Reports</div>', unsafe_allow_html=True)
        exp_run_id = sel_run if sel_run != "ALL" else None
        dl1, dl2 = st.columns(2)
        with dl1:
            csv_data = build_accuracy_report_csv(evaluations, run_id=exp_run_id)
            st.download_button(
                "Download FinovaLabs Accuracy CSV",
                data=csv_data,
                file_name=f"finovalabs_accuracy_{exp_run_id or 'all'}.csv",
                mime="text/csv",
                **stretch_width_kwargs(st.download_button),
            )
        with dl2:
            json_data = build_accuracy_report_json(evaluations, run_id=exp_run_id)
            st.download_button(
                "Download FinovaLabs Accuracy JSON",
                data=json_data,
                file_name=f"finovalabs_accuracy_{exp_run_id or 'all'}.json",
                mime="application/json",
                **stretch_width_kwargs(st.download_button),
            )
    else:
        render_empty_state(
            title="No accuracy benchmark results yet",
            description=(
                "Accuracy metrics compare raw automated extraction and final post-review values against "
                "official SEC Company Facts XBRL entries with strict company, concept, fiscal period, "
                "and unit checks."
            ),
            badge_label="Awaiting Evaluation",
            next_step="Click 'Evaluate vs. SEC Facts' above once a filing workflow has been executed.",
        )

    render_footer()


def render_audit_trail_page() -> None:
    """Render the tamper-evident Audit Trail ledger with SQL filters & decision history."""
    settings, posture_summary = _bootstrap_page("Audit Trail", active_step=5)
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
        title="Audit Trail",
        subtitle=(
            "Inspect the chronological, filterable ledger of human review decisions "
            "and workflow events protected by SHA-256 hash chaining."
        ),
        status_label=(
            f"Chain Intact • {event_total} Events"
            if chain_valid
            else "Chain Verification Alert"
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
                "Use filters below (Company, UTC Date, Decision, Metric, Workflow ID) to narrow history, or click "
                "'Re-Verify Audit Hash Chain' and 'Download Audit Ledger JSON'."
            ),
            expected_result=(
                "Verifies every sequential seq_id and SHA-256 link end-to-end, lists Original vs. Corrected values, "
                "and exports complete compliance provenance."
            ),
        )
    with aud_g2:
        render_field_tooltips_popover()

    st.info(TAMPER_EVIDENT_NOTICE)

    render_metric_cards(
        [
            {
                "label": "Ledger Events",
                "value": str(event_total),
                "detail": "Append-only SQLite audit_events",
            },
            {
                "label": "Chain Integrity",
                "value": "Verified" if chain_valid else "Tamper Detected",
                "detail": failure_reason or "Sequential seq_id + SHA-256 verified",
            },
            {
                "label": "Human Decisions",
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
                "label": "Log Destination",
                "value": settings.logging.level,
                "detail": str(settings.log_file),
            },
        ]
    )

    btn_c1, btn_c2, btn_c3 = st.columns([1.4, 1.4, 1.2])
    with btn_c1:
        if st.button("Re-Verify Audit Hash Chain", type="primary", **stretch_width_kwargs(st.button)):
            with st.spinner("Verifying sequential SHA-256 hash links..."):
                recheck = safe_execute(verify_audit_chain, "manual hash-chain verification")
            if recheck and recheck[0]:
                st.success(f"Cryptographic chain verified across {recheck[1]} event(s) (tamper-evident).")
            elif recheck:
                st.error(f"Chain integrity error: {recheck[2]}")
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
            "Download Audit Ledger JSON",
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
            help_text="Start or inspect another company's 10-K audit workflow.",
        )

    # Interactive SQLite-backed filters: Company, Date (UTC), Decision, Metric, Workflow ID, Sort & Telemetry scope
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
            help="Filter by human decision (APPROVED, CORRECTED, REJECTED) or system event type.",
        )
    with fc4:
        sel_metric = st.selectbox("Metric", ["ALL", *metric_opts], key="audit_filter_metric")

    fc5, fc6, fc7 = st.columns([1.2, 1.8, 1.0])
    with fc5:
        sel_run_id = st.selectbox("Workflow Run ID", ["ALL", *run_ids], key="audit_run_id")
    with fc6:
        search_q = st.text_input(
            "Search Reviewer / Session / Filing / Explanation",
            value="",
            key="audit_search",
            placeholder="e.g., analyst, 0000320193, Net Income...",
        ).strip().lower()
    with fc7:
        sort_order = st.selectbox(
            "Chronological Order",
            ["Newest First", "Oldest First"],
            key="audit_sort_order",
            help="Order records by sequential ledger ID (`seq_id`) and UTC timestamp.",
        )

    include_telemetry = st.checkbox(
        "Include low-level automated system telemetry in full ledger table",
        value=False,
        key="audit_include_telemetry",
        help=(
            "When unchecked, the lower ledger highlights human decisions, workflow starts/completions, "
            "accuracy runs, and checkpoint milestones while hiding repetitive per-metric system checks."
        ),
    )

    if len(all_events) >= 500:
        st.caption("Showing the most recent 500 events loaded from SQLite. Export JSON or filter to narrow scope.")

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

    st.markdown('<div class="fl-section-title">Reviewer Decisions (Append-Only Decision History)</div>', unsafe_allow_html=True)
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
                "Seq #",
                "Timestamp (UTC)",
                "Reviewer / Session",
                "Workflow ID",
                "Company / Filing",
                "Metric",
                "Decision",
                "Original Value",
                "Corrected Value",
                "Explanation",
            ],
            rows=dec_rows,
            right_align_cols={0, 7, 8},
        )
    else:
        render_empty_state(
            title="No human review decisions match filters",
            description=(
                "Every human approval, correction, rejection, and subsequent amendment appends a permanent "
                "record here with original and corrected values."
            ),
            badge_label="No Decision Matches",
        )

    if filtered_events:
        ev_counts: dict[str, int] = {}
        for ev in filtered_events:
            label = ev.get("decision") or ev["event_type"]
            ev_counts[label] = ev_counts.get(label, 0) + 1
        ev_df = pd.DataFrame(
            [{"Decision / Event": k, "Count": v} for k, v in sorted(ev_counts.items())]
        )
        fig_ev = px.bar(
            ev_df,
            x="Decision / Event",
            y="Count",
            color_discrete_sequence=["#1D4ED8"],
        )
        render_plotly_chart(
            fig_ev,
            title="Filtered Audit Records by Decision / Event Type",
            key="audit_events_plotly",
            height=280,
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

    st.markdown('<div class="fl-section-title">Tamper-Evident Append-Only Audit Ledger</div>', unsafe_allow_html=True)
    if not include_telemetry and sel_decision == "ALL" and len(filtered_events) > len(ledger_events):
        st.caption(
            f"Showing {len(ledger_events)} milestone & decision event(s) ({len(filtered_events) - len(ledger_events)} "
            "low-level automated telemetry records hidden — toggle checkbox above to inspect all)."
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
                ("Linked", "success"),
            ]
            for ev in ledger_events
        ]
        render_status_table(
            headers=[
                "Seq #",
                "UTC Time",
                "Company",
                "Filing",
                "Metric",
                "Decision",
                "Original",
                "Corrected",
                "Reviewer / Session",
                "Workflow ID",
                "Hash",
                "Chain",
            ],
            rows=rows,
            right_align_cols={0, 6, 7},
        )
        with st.expander("Inspect Event Payloads, Explanations & SHA-256 Chain Links", expanded=False):
            for ev in ledger_events[:50]:
                st.markdown(
                    f"**Seq #{ev.get('seq_id') or ev['event_id']} (`event_id={ev['event_id']}`) • "
                    f"{humanize_status(ev.get('decision') or ev['event_type'])}** (`{ev['created_at']}`) — "
                    f"Reviewer: `{ev.get('reviewer_id') or ev['actor']}` | Session: `{ev.get('session_id') or '—'}` | "
                    f"Company: `{ev.get('ticker') or ev.get('cik') or '—'}` | Filing: `{ev.get('accession_number') or '—'}` | "
                    f"Metric: `{ev.get('metric_name') or '—'}` | Workflow: `{ev.get('run_id') or '—'}`  \n"
                    f"Explanation: {ev.get('explanation') or '—'}  \n"
                    f"Original Value: `{ev.get('original_value') or '—'}` | Corrected Value: `{ev.get('corrected_value') or '—'}`  \n"
                    f"Prev Hash: `{ev['prev_hash'][:16]}…` -> Event Hash: `{ev['event_hash'][:16]}…`"
                )
                st.code(ev["payload_json"], language="json")
    else:
        render_empty_state(
            title="Audit ledger has no matching events",
            description=(
                "The tamper-evident SHA-256 audit table is initialized and verified "
                "in SQLite (tamper-evident, not absolutely tamper-proof). Events append "
                "automatically as workflows decide, extract, validate, and capture human reviews."
            ),
            badge_label="Genesis State Verified" if not all_events else "No Filter Matches",
            next_step="Adjust filters or enable low-level automated telemetry above.",
        )

    render_footer()

