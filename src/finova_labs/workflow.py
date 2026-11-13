"""LangGraph SQLite-checkpointed workflow orchestration with idempotency and restart recovery."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from finova_labs.audit import record_audit_event
from finova_labs.database import (
    amend_metric_review_decision,
    claim_idempotency_key,
    create_audit_run,
    fetch_audit_run,
    fetch_audit_run_by_idempotency_key,
    fetch_extracted_metrics,
    fetch_open_review_count_for_run,
    fetch_review_tasks,
    fetch_validation_results,
    get_connection,
    get_idempotency_record,
    init_db,
    is_postgres_configured,
    record_human_review_decision,
    resolve_db_path,
    sync_review_tasks_for_filing,
    update_audit_run_status,
)
from finova_labs.exceptions import WorkflowError
from finova_labs.extractor import (
    CandidateFact,
    ExtractedMetricRecord,
    extract_metrics_for_filing,
)
from finova_labs.logging_config import get_logger
from finova_labs.metric_mapping import MetricDefinition
from finova_labs.sec_client import FilingMetadata, SecEdgarClient
from finova_labs.settings import ConfidenceSettings, ValidationSettings, get_settings
from finova_labs.validators import PriorPeriodPoint, SegmentRevenueItem, run_financial_validations

logger = get_logger("workflow")

# Transient runtime payload map keyed by run_id so large HTML/CompanyFacts blobs do not bloat
# LangGraph SQLite checkpoints. Entries are popped once validate_and_gate completes.
_RUN_INPUT_CACHE: dict[str, dict[str, Any]] = {}


class WorkflowState(TypedDict):
    """Serializable LangGraph workflow state persisted via SqliteSaver."""

    run_id: str
    idempotency_key: str | None
    cik: str
    ticker: str | None
    company_name: str | None
    accession_number: str
    form_type: str
    fiscal_year: int | None
    filing_dict: dict[str, Any]
    db_path: str
    extraction_done: bool
    validation_done: bool
    auto_approved_metrics: list[str]
    escalated_metrics: list[str]
    escalation_reasons: dict[str, str]
    overall_confidence: float | None
    paused_for_review: bool
    human_decisions: list[dict[str, Any]]
    finalized: bool
    status: str
    current_stage: str
    executed_nodes: list[str]


class WorkflowOutcome(BaseModel):
    """Structured result returned when starting, pausing, or resuming an audit workflow."""

    run_id: str
    idempotency_key: str | None = None
    status: str
    current_stage: str = "STARTED"
    paused: bool
    overall_confidence: float | None = None
    auto_approved_metrics: list[str] = Field(default_factory=list)
    escalated_metrics: list[str] = Field(default_factory=list)
    open_task_count: int = 0
    executed_nodes: list[str] = Field(default_factory=list)
    finalized: bool = False
    reused_existing_run: bool = False
    checkpoint_backend: str = "langgraph.checkpoint.sqlite.SqliteSaver"


def build_workflow_idempotency_key(
    filing: FilingMetadata,
    *,
    include_html: bool = True,
    confidence_settings: ConfidenceSettings | None = None,
    validation_settings: ValidationSettings | None = None,
) -> str:
    """Build a deterministic idempotency key for a filing run and rule configuration."""
    settings = get_settings()
    conf = confidence_settings or settings.confidence
    val = validation_settings or settings.validation
    raw = "|".join(
        [
            filing.cik,
            filing.accession_number,
            f"html={int(include_html)}",
            f"score_v={conf.scoring_version}",
            f"conf_thr={conf.auto_approve_threshold:.4f}",
            f"yoy_thr={val.yoy_change_alert_threshold:.4f}",
        ]
    )
    return f"wf-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


@contextmanager
def _open_checkpointer(db_path: Path | str | None = None) -> Iterator[Any]:
    """Open and initialize LangGraph checkpointer (PostgresSaver when configured, else SQLite SqliteSaver)."""
    if is_postgres_configured(db_path):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        db_url = get_settings().database_url
        with ConnectionPool(conninfo=db_url, min_size=1, max_size=5, kwargs={"autocommit": True}) as pool:
            checkpointer = PostgresSaver(pool)
            checkpointer.setup()
            yield checkpointer
        return

    target = resolve_db_path(db_path)
    init_db(target)
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=15.0)
    try:
        saver = SqliteSaver(conn)
        saver.setup()
        yield saver
    finally:
        conn.close()


def _load_records_from_db(
    run_id: str,
    accession_number: str,
    db_path: Path,
) -> list[ExtractedMetricRecord]:
    """Reconstruct ExtractedMetricRecord objects from SQLite for crash/restart recovery."""
    rows = fetch_extracted_metrics(run_id=run_id, accession_number=accession_number, db_path=db_path, limit=200)
    records: list[ExtractedMetricRecord] = []
    for row in rows:
        dec_val: Decimal | None = None
        if row.get("normalized_decimal") is not None:
            dec_val = Decimal(str(row["normalized_decimal"]))
        elif row.get("normalized_value") is not None:
            dec_val = Decimal(str(row["normalized_value"]))

        cands: list[CandidateFact] = []
        raw_cands = row.get("candidates_json")
        if raw_cands:
            try:
                cands = [CandidateFact.model_validate(item) for item in json.loads(raw_cands)]
            except Exception:
                cands = []

        reasons: list[str] = []
        raw_reasons = row.get("confidence_reasons")
        if raw_reasons:
            try:
                reasons = list(json.loads(raw_reasons))
            except Exception:
                reasons = []

        comp: dict[str, Any] | None = None
        raw_comp = row.get("confidence_components_json")
        if raw_comp:
            try:
                comp = json.loads(raw_comp)
            except Exception:
                comp = None

        records.append(
            ExtractedMetricRecord(
                cik=row["cik"],
                ticker=row.get("ticker"),
                accession_number=row["accession_number"],
                form_type=row.get("form_type") or "10-K",
                metric_name=row["metric_name"],
                xbrl_concept=row.get("xbrl_concept"),
                raw_value=row.get("raw_value"),
                normalized_value=dec_val,
                reported_unit=row.get("unit") or "USD",
                currency=row.get("currency") or "USD",
                scale_factor=Decimal(str(row.get("scale_factor") or 1)),
                fiscal_period=row.get("fiscal_period") or "FY",
                fiscal_year=row.get("fiscal_year"),
                period_start=row.get("period_start"),
                period_end=row.get("period_end"),
                source_url=row.get("source_url") or "",
                evidence_snippet=row.get("source_evidence") or "",
                evidence_location=row.get("evidence_location") or "",
                extraction_status=row.get("extraction_status") or "EXTRACTED",
                review_status=row.get("review_status") or "NOT_REQUIRED",
                validation_status=row.get("validation_status") or "PENDING",
                confidence_score=row.get("confidence_score"),
                confidence_components=comp,
                confidence_reasons=reasons,
                confidence_threshold=row.get("confidence_threshold"),
                scoring_version=row.get("scoring_version"),
                candidates=cands,
                created_at=row["created_at"],
            )
        )
    return records


def _extract_and_score_node(state: WorkflowState) -> dict[str, Any]:
    """Node 1: Extract 8 financial metrics and score confidence (guarded by idempotency key)."""
    if state.get("extraction_done"):
        return {}

    run_id = state["run_id"]
    db_path = Path(state["db_path"])
    filing = FilingMetadata.model_validate(state["filing_dict"])
    stage_key = f"stage:extract_and_score:{run_id}"
    if get_idempotency_record(stage_key, db_path=db_path) is not None:
        records = _load_records_from_db(run_id, filing.accession_number, db_path)
        scores = [r.confidence_score for r in records if r.confidence_score is not None]
        overall_conf = round(sum(scores) / len(scores), 4) if scores else state.get("overall_confidence")
        return {
            "extraction_done": True,
            "overall_confidence": overall_conf,
            "current_stage": "EXTRACTED_AND_SCORED",
        }

    runtime_inputs = _RUN_INPUT_CACHE.get(run_id, {})
    company_facts = runtime_inputs.get("company_facts")
    html_text = runtime_inputs.get("html_text")
    metrics_override: tuple[MetricDefinition, ...] | None = runtime_inputs.get("metrics")
    conf_settings: ConfidenceSettings | None = runtime_inputs.get("confidence_settings")

    if company_facts is None:
        client = SecEdgarClient()
        company_facts = client.get_company_facts(filing.cik).facts
        if html_text is None and runtime_inputs.get("include_html", True):
            html_text, _, _ = client.get_filing_html(
                filing_url=filing.filing_url,
                cik=filing.cik,
                accession_number=filing.accession_number,
                primary_document=filing.primary_document,
            )

    records = extract_metrics_for_filing(
        filing=filing,
        company_facts=company_facts,
        html_text=html_text,
        metrics=metrics_override,
        persist=True,
        run_id=run_id,
        db_path=db_path,
        confidence_settings=conf_settings,
        run_validations=False,
    )

    scores = [r.confidence_score for r in records if r.confidence_score is not None]
    overall_conf = round(sum(scores) / len(scores), 4) if scores else None
    claim_idempotency_key(
        idempotency_key=stage_key,
        scope="workflow_stage",
        target_id=run_id,
        db_path=db_path,
    )
    update_audit_run_status(
        run_id=run_id,
        status="RUNNING",
        current_stage="EXTRACTED_AND_SCORED",
        overall_confidence=overall_conf,
        db_path=db_path,
    )

    runtime_inputs["records"] = records
    runtime_inputs["company_facts"] = company_facts
    runtime_inputs["html_text"] = html_text
    _RUN_INPUT_CACHE[run_id] = runtime_inputs

    return {
        "extraction_done": True,
        "overall_confidence": overall_conf,
        "current_stage": "EXTRACTED_AND_SCORED",
        "executed_nodes": [*state.get("executed_nodes", []), "extract_and_score"],
    }


def _build_combined_escalation_reason(
    metric_row: dict[str, Any],
    failed_validations: list[dict[str, Any]],
) -> str:
    """Create a clear single-line reason citing confidence/extraction and validation failures."""
    parts: list[str] = []
    ext_status = str(metric_row.get("extraction_status") or "EXTRACTED")
    score = metric_row.get("confidence_score")
    threshold = metric_row.get("confidence_threshold")

    if ext_status != "EXTRACTED":
        parts.append(f"Extraction status is {ext_status}")
    if score is not None and threshold is not None and score < threshold:
        parts.append(f"Confidence {score:.1%} < threshold {threshold:.1%}")
        raw_reasons = metric_row.get("confidence_reasons")
        if raw_reasons:
            try:
                reasons_list = json.loads(raw_reasons)
                if reasons_list:
                    parts.append(reasons_list[-1])
            except ValueError:
                pass

    for f_val in failed_validations:
        parts.append(f"Validation FAIL ({f_val['rule_name']}): {f_val['explanation']}")

    return " | ".join(parts) if parts else "Requires mandatory analyst review."


def _validate_and_gate_node(state: WorkflowState) -> dict[str, Any]:
    """Node 2: Run financial validations and evaluate the mandatory auto-approval gate."""
    if state.get("validation_done"):
        return {}

    run_id = state["run_id"]
    db_path = Path(state["db_path"])
    filing = FilingMetadata.model_validate(state["filing_dict"])
    runtime_inputs = _RUN_INPUT_CACHE.get(run_id, {})

    records: list[ExtractedMetricRecord] | None = runtime_inputs.get("records")
    if records is None:
        # Recover records directly from SQLite after restart without re-running extraction
        records = _load_records_from_db(run_id, filing.accession_number, db_path)
        if not records:
            raise WorkflowError(
                f"Cannot recover extracted metrics for workflow '{run_id}' from SQLite."
            )

    company_facts = runtime_inputs.get("company_facts")
    html_text = runtime_inputs.get("html_text")
    val_settings: ValidationSettings | None = runtime_inputs.get("validation_settings")
    segment_items: list[SegmentRevenueItem] | None = runtime_inputs.get("segment_items")
    prior_records = runtime_inputs.get("prior_records")
    prior_points: dict[str, PriorPeriodPoint] | None = runtime_inputs.get("prior_points")

    stage_key = f"stage:validate_and_gate:{run_id}"
    if get_idempotency_record(stage_key, db_path=db_path) is None:
        run_financial_validations(
            records,
            cik=filing.cik,
            ticker=filing.ticker,
            accession_number=filing.accession_number,
            company_facts=company_facts,
            html_text=html_text,
            segment_items=segment_items,
            prior_records=prior_records,
            prior_points=prior_points,
            settings=val_settings,
            persist=True,
            run_id=run_id,
            db_path=db_path,
        )
        claim_idempotency_key(
            idempotency_key=stage_key,
            scope="workflow_stage",
            target_id=run_id,
            db_path=db_path,
        )

    stored_metrics = fetch_extracted_metrics(
        run_id=run_id,
        accession_number=filing.accession_number,
        db_path=db_path,
        limit=200,
    )
    stored_vals = fetch_validation_results(
        accession_number=filing.accession_number,
        status="FAIL",
        db_path=db_path,
        limit=200,
    )

    failed_by_metric: dict[str, list[dict[str, Any]]] = {}
    for val in stored_vals:
        refs = []
        try:
            refs = json.loads(val.get("input_metric_refs_json") or "[]")
        except ValueError:
            refs = []
        referenced_names = {r.get("metric_name") for r in refs if r.get("metric_name")}
        if val.get("metric_name") == "Accounting Equation (A = L + E)":
            referenced_names.update({"Total Assets", "Total Liabilities", "Shareholders' Equity"})
        if val.get("metric_name") == "Segment Revenue Reconciliation":
            referenced_names.add("Revenue")
        for m_name in referenced_names:
            failed_by_metric.setdefault(m_name, []).append(val)

    auto_approved: list[str] = []
    escalated: list[str] = []
    escalation_reasons: dict[str, str] = {}
    review_task_payloads: list[dict[str, Any]] = []
    gating_events: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for row in stored_metrics:
        m_name = row["metric_name"]
        ext_ok = row.get("extraction_status") == "EXTRACTED" and row.get("normalized_value") is not None
        score = row.get("confidence_score")
        threshold = row.get("confidence_threshold")
        if threshold is None:
            threshold = get_settings().confidence.auto_approve_threshold
        conf_ok = score is not None and score >= threshold
        val_ok = row.get("validation_status") != "FAIL" and not failed_by_metric.get(m_name)
        orig_str = (
            str(row["normalized_decimal"])
            if row.get("normalized_decimal") is not None
            else (str(row["normalized_value"]) if row.get("normalized_value") is not None else None)
        )

        if ext_ok and conf_ok and val_ok:
            auto_approved.append(m_name)
            gating_events.append(
                {
                    "metric_id": row["id"],
                    "metric_name": m_name,
                    "decision": "AUTO_APPROVED",
                    "original_value": orig_str,
                    "explanation": (
                        f"Auto-approved by workflow: confidence {score:.1%} >= {threshold:.1%} "
                        f"and mandatory validations passed."
                    ),
                }
            )
        else:
            escalated.append(m_name)
            reason = _build_combined_escalation_reason(row, failed_by_metric.get(m_name, []))
            escalation_reasons[m_name] = reason
            review_task_payloads.append(
                {
                    "run_id": run_id,
                    "ticker": filing.ticker,
                    "metric_id": row["id"],
                    "metric_name": m_name,
                    "reason": reason,
                    "created_at": now,
                }
            )
            gating_events.append(
                {
                    "metric_id": row["id"],
                    "metric_name": m_name,
                    "decision": "ESCALATED",
                    "original_value": orig_str,
                    "explanation": reason,
                }
            )

    paused = len(escalated) > 0
    next_stage = "PAUSED_FOR_REVIEW" if paused else "VALIDATED"

    with get_connection(db_path) as conn:
        filing_row = conn.execute(
            "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
            (filing.cik, filing.accession_number),
        ).fetchone()
        filing_id = int(filing_row["id"]) if filing_row else None

        for row in stored_metrics:
            new_rev_status = "AUTO_APPROVED" if row["metric_name"] in auto_approved else "REVIEW_REQUIRED"
            conn.execute(
                "UPDATE extracted_metrics SET review_status = ? WHERE id = ?",
                (new_rev_status, row["id"]),
            )

        sync_review_tasks_for_filing(
            tasks=review_task_payloads,
            cik=filing.cik,
            accession_number=filing.accession_number,
            db_path=db_path,
            conn=conn,
        )

        gate_ev_key = f"event:gate_decisions:{run_id}"
        gate_claimed, _ = claim_idempotency_key(
            idempotency_key=gate_ev_key,
            scope="audit_event",
            target_id=run_id,
            db_path=db_path,
            conn=conn,
        )
        if gate_claimed:
            for item in gating_events:
                record_audit_event(
                    event_type="WORKFLOW_DECISION",
                    actor="workflow",
                    run_id=run_id,
                    cik=filing.cik,
                    ticker=filing.ticker,
                    company_name=filing.company_name,
                    filing_id=filing_id,
                    accession_number=filing.accession_number,
                    metric_id=item["metric_id"],
                    metric_name=item["metric_name"],
                    decision=item["decision"],
                    original_value=item["original_value"],
                    corrected_value=None,
                    reviewer_id="workflow",
                    explanation=item["explanation"],
                    payload={
                        "cik": filing.cik,
                        "ticker": filing.ticker,
                        "company_name": filing.company_name,
                        "filing_id": filing_id,
                        "accession_number": filing.accession_number,
                        "metric_id": item["metric_id"],
                        "metric_name": item["metric_name"],
                        "decision": item["decision"],
                        "original_decimal": item["original_value"],
                        "explanation": item["explanation"],
                    },
                    conn=conn,
                )

        if paused:
            update_audit_run_status(
                run_id=run_id,
                status="PAUSED_FOR_REVIEW",
                current_stage="PAUSED_FOR_REVIEW",
                db_path=db_path,
                conn=conn,
            )
            pause_ev_key = f"event:paused:{run_id}"
            ev_claimed, _ = claim_idempotency_key(
                idempotency_key=pause_ev_key,
                scope="audit_event",
                target_id=run_id,
                db_path=db_path,
                conn=conn,
            )
            if ev_claimed:
                record_audit_event(
                    event_type="WORKFLOW_PAUSED_FOR_REVIEW",
                    actor="workflow",
                    run_id=run_id,
                    cik=filing.cik,
                    ticker=filing.ticker,
                    company_name=filing.company_name,
                    filing_id=filing_id,
                    accession_number=filing.accession_number,
                    decision="WORKFLOW_PAUSED",
                    explanation=f"Paused for analyst review on {len(escalated)} metric(s).",
                    payload={
                        "cik": filing.cik,
                        "ticker": filing.ticker,
                        "company_name": filing.company_name,
                        "filing_id": filing_id,
                        "accession_number": filing.accession_number,
                        "auto_approved_count": len(auto_approved),
                        "escalated_metrics": escalated,
                    },
                    conn=conn,
                )
        else:
            update_audit_run_status(
                run_id=run_id,
                status="RUNNING",
                current_stage="VALIDATED",
                db_path=db_path,
                conn=conn,
            )

    _RUN_INPUT_CACHE.pop(run_id, None)

    return {
        "validation_done": True,
        "auto_approved_metrics": auto_approved,
        "escalated_metrics": escalated,
        "escalation_reasons": escalation_reasons,
        "paused_for_review": paused,
        "status": "PAUSED_FOR_REVIEW" if paused else "RUNNING",
        "current_stage": next_stage,
        "executed_nodes": [*state.get("executed_nodes", []), "validate_and_gate"],
    }


def _route_after_validation(state: WorkflowState) -> str:
    """Route to human_review when any metric failed confidence or mandatory validations."""
    return "human_review" if state.get("escalated_metrics") else "finalize"


def _human_review_node(state: WorkflowState) -> dict[str, Any]:
    """Node 3: Pause execution cleanly via LangGraph interrupt until analyst decisions arrive."""
    payload = {
        "run_id": state["run_id"],
        "cik": state["cik"],
        "ticker": state.get("ticker"),
        "accession_number": state["accession_number"],
        "escalated_metrics": state.get("escalated_metrics", []),
        "reasons": state.get("escalation_reasons", {}),
    }
    decisions = interrupt(payload)
    normalized = decisions if isinstance(decisions, list) else [decisions]
    return {
        "paused_for_review": False,
        "human_decisions": normalized,
        "current_stage": "REVIEWED",
        "executed_nodes": [*state.get("executed_nodes", []), "human_review"],
    }


def _finalize_node(state: WorkflowState) -> dict[str, Any]:
    """Node 4: Mark run COMPLETED once all escalated items are resolved (idempotent)."""
    if state.get("finalized"):
        return {}

    run_id = state["run_id"]
    db_path = Path(state["db_path"])
    remaining_open = fetch_open_review_count_for_run(run_id, db_path=db_path)
    if remaining_open > 0:
        raise WorkflowError(
            f"Cannot finalize workflow '{run_id}': {remaining_open} review task(s) remain OPEN."
        )

    stored_metrics = fetch_extracted_metrics(
        run_id=run_id,
        accession_number=state["accession_number"],
        db_path=db_path,
        limit=200,
    )
    rejected_metrics = [m["metric_name"] for m in stored_metrics if m.get("review_status") == "REJECTED"]
    corrected_metrics = [m["metric_name"] for m in stored_metrics if m.get("review_status") == "CORRECTED"]
    final_status = "COMPLETED_WITH_REJECTIONS" if rejected_metrics else "COMPLETED"

    update_needed_eval = False
    with get_connection(db_path) as conn:
        filing_row = conn.execute(
            "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
            (state["cik"], state["accession_number"]),
        ).fetchone()
        filing_id = int(filing_row["id"]) if filing_row else None

        update_audit_run_status(
            run_id=run_id,
            status=final_status,
            current_stage="FINALIZED",
            db_path=db_path,
            conn=conn,
        )

        fin_key = f"stage:finalize:{run_id}"
        claimed, _ = claim_idempotency_key(
            idempotency_key=fin_key,
            scope="workflow_stage",
            target_id=run_id,
            db_path=db_path,
            conn=conn,
        )
        if claimed:
            update_needed_eval = True
            if state.get("escalated_metrics"):
                record_audit_event(
                    event_type="WORKFLOW_RESUMED",
                    actor="workflow",
                    run_id=run_id,
                    cik=state["cik"],
                    ticker=state.get("ticker"),
                    company_name=state.get("company_name"),
                    filing_id=filing_id,
                    accession_number=state["accession_number"],
                    decision="WORKFLOW_RESUMED",
                    explanation=f"Workflow resumed after {len(state.get('human_decisions', []))} analyst decision(s).",
                    payload={
                        "cik": state["cik"],
                        "ticker": state.get("ticker"),
                        "company_name": state.get("company_name"),
                        "filing_id": filing_id,
                        "accession_number": state["accession_number"],
                        "decisions_applied": len(state.get("human_decisions", [])),
                    },
                    conn=conn,
                )

            record_audit_event(
                event_type="WORKFLOW_COMPLETED",
                actor="workflow",
                run_id=run_id,
                cik=state["cik"],
                ticker=state.get("ticker"),
                company_name=state.get("company_name"),
                filing_id=filing_id,
                accession_number=state["accession_number"],
                decision=final_status,
                explanation=(
                    f"Workflow finalized with status {final_status}: "
                    f"{len(state.get('auto_approved_metrics', []))} auto-approved, "
                    f"{len(corrected_metrics)} corrected, {len(rejected_metrics)} rejected."
                ),
                payload={
                    "cik": state["cik"],
                    "ticker": state.get("ticker"),
                    "company_name": state.get("company_name"),
                    "filing_id": filing_id,
                    "accession_number": state["accession_number"],
                    "final_status": final_status,
                    "auto_approved_metrics": state.get("auto_approved_metrics", []),
                    "corrected_metrics": corrected_metrics,
                    "rejected_metrics": rejected_metrics,
                },
                conn=conn,
            )

    if update_needed_eval:
        # Auto-evaluate against locally cached SEC Company Facts if already on disk (zero network side effects)
        try:
            from finova_labs.evaluation import (
                _load_cached_company_facts,
                evaluate_run_against_company_facts,
            )

            cached_facts = _load_cached_company_facts(state["cik"])
            if cached_facts is not None:
                evaluate_run_against_company_facts(
                    run_id,
                    company_facts=cached_facts,
                    use_cached_only=True,
                    persist=True,
                    db_path=db_path,
                )
        except Exception as exc:
            logger.warning("Skipping auto accuracy evaluation on finalize for %s: %s", run_id, exc)

    return {
        "finalized": True,
        "paused_for_review": False,
        "status": final_status,
        "current_stage": "FINALIZED",
        "executed_nodes": [*state.get("executed_nodes", []), "finalize"],
    }


def _compile_workflow_graph(checkpointer: Any) -> Any:
    """Build and compile the FinovaLabs LangGraph state machine."""
    builder: StateGraph = StateGraph(WorkflowState)
    builder.add_node("extract_and_score", _extract_and_score_node)
    builder.add_node("validate_and_gate", _validate_and_gate_node)
    builder.add_node("human_review", _human_review_node)
    builder.add_node("finalize", _finalize_node)

    builder.add_edge(START, "extract_and_score")
    builder.add_edge("extract_and_score", "validate_and_gate")
    builder.add_conditional_edges(
        "validate_and_gate",
        _route_after_validation,
        {
            "human_review": "human_review",
            "finalize": "finalize",
        },
    )
    builder.add_edge("human_review", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


def _outcome_from_result(
    run_id: str,
    result_state: dict[str, Any],
    db_path: Path,
    *,
    reused_existing_run: bool = False,
) -> WorkflowOutcome:
    is_interrupted = bool(result_state.get("__interrupt__")) or bool(result_state.get("paused_for_review"))
    open_count = fetch_open_review_count_for_run(run_id, db_path=db_path)
    backend_name = (
        "langgraph.checkpoint.postgres.PostgresSaver"
        if is_postgres_configured()
        else "langgraph.checkpoint.sqlite.SqliteSaver"
    )
    return WorkflowOutcome(
        run_id=run_id,
        idempotency_key=result_state.get("idempotency_key"),
        status="PAUSED_FOR_REVIEW" if is_interrupted else str(result_state.get("status") or "COMPLETED"),
        current_stage=str(result_state.get("current_stage") or ("PAUSED_FOR_REVIEW" if is_interrupted else "FINALIZED")),
        paused=is_interrupted,
        overall_confidence=result_state.get("overall_confidence"),
        auto_approved_metrics=list(result_state.get("auto_approved_metrics", [])),
        escalated_metrics=list(result_state.get("escalated_metrics", [])),
        open_task_count=open_count,
        executed_nodes=list(result_state.get("executed_nodes", [])),
        finalized=bool(result_state.get("finalized")),
        reused_existing_run=reused_existing_run,
        checkpoint_backend=backend_name,
    )


def _record_interruption_status(
    run_id: str,
    exc: Exception,
    target_db: Path,
) -> None:
    """Persist INTERRUPTED when recoverable stage checkpoints exist, else FAILED (with audit atomically)."""
    checkpoint_state = get_workflow_checkpoint_state(run_id, db_path=target_db)
    is_recoverable = bool(
        checkpoint_state and (checkpoint_state.get("extraction_done") or checkpoint_state.get("validation_done"))
    )
    new_status = "INTERRUPTED" if is_recoverable else "FAILED"
    with get_connection(target_db) as conn:
        run_row = conn.execute(
            "SELECT cik, ticker, company_name, filing_id, accession_number FROM audit_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        update_audit_run_status(
            run_id=run_id,
            status=new_status,
            error_message=str(exc),
            db_path=target_db,
            conn=conn,
        )
        record_audit_event(
            event_type="WORKFLOW_INTERRUPTED" if is_recoverable else "WORKFLOW_FAILED",
            actor="workflow",
            run_id=run_id,
            cik=run_row["cik"] if run_row else None,
            ticker=run_row["ticker"] if run_row else None,
            company_name=run_row["company_name"] if run_row else None,
            filing_id=run_row["filing_id"] if run_row else None,
            accession_number=run_row["accession_number"] if run_row else None,
            decision=new_status,
            explanation=str(exc),
            payload={
                "status": new_status,
                "current_stage": checkpoint_state.get("current_stage") if checkpoint_state else "STARTED",
                "error": str(exc),
            },
            conn=conn,
        )


def start_audit_workflow(
    filing: FilingMetadata,
    *,
    company_facts: dict[str, Any] | None = None,
    html_text: str | None = None,
    include_html: bool = True,
    metrics: tuple[MetricDefinition, ...] | None = None,
    segment_items: list[SegmentRevenueItem] | None = None,
    prior_records: list[ExtractedMetricRecord] | dict[str, ExtractedMetricRecord] | None = None,
    prior_points: dict[str, PriorPeriodPoint] | None = None,
    run_id: str | None = None,
    idempotency_key: str | None = None,
    force_new_run: bool = False,
    confidence_settings: ConfidenceSettings | None = None,
    validation_settings: ValidationSettings | None = None,
    db_path: Path | str | None = None,
) -> WorkflowOutcome:
    """Start or idempotently recover a checkpointed LangGraph audit run."""
    target_db = resolve_db_path(db_path)
    init_db(target_db)

    resolved_key: str | None = None
    if not force_new_run:
        resolved_key = idempotency_key or build_workflow_idempotency_key(
            filing,
            include_html=include_html,
            confidence_settings=confidence_settings,
            validation_settings=validation_settings,
        )
        existing = fetch_audit_run_by_idempotency_key(resolved_key, db_path=target_db)
        if existing is not None:
            existing_run_id = existing["run_id"]
            cp_state = get_workflow_checkpoint_state(existing_run_id, db_path=target_db)
            if existing["status"] in {"COMPLETED", "COMPLETED_WITH_REJECTIONS"} and cp_state is not None:
                return _outcome_from_result(
                    existing_run_id,
                    cp_state,
                    target_db,
                    reused_existing_run=True,
                )
            if existing["status"] == "PAUSED_FOR_REVIEW" and cp_state is not None:
                return _outcome_from_result(
                    existing_run_id,
                    cp_state,
                    target_db,
                    reused_existing_run=True,
                )
            if existing["status"] in {"RUNNING", "INTERRUPTED", "PENDING"} and cp_state is not None:
                _RUN_INPUT_CACHE[existing_run_id] = {
                    "company_facts": company_facts,
                    "html_text": html_text,
                    "include_html": include_html,
                    "metrics": metrics,
                    "segment_items": segment_items,
                    "prior_records": prior_records,
                    "prior_points": prior_points,
                    "confidence_settings": confidence_settings,
                    "validation_settings": validation_settings,
                }
                resumed = resume_audit_workflow(existing_run_id, db_path=target_db)
                resumed.reused_existing_run = True
                return resumed

    assigned_run_id = run_id or f"run-{uuid.uuid4().hex[:10]}"
    with get_connection(target_db) as conn:
        filing_row = conn.execute(
            "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
            (filing.cik, filing.accession_number),
        ).fetchone()
        filing_id = int(filing_row["id"]) if filing_row else None
        create_audit_run(
            run_id=assigned_run_id,
            cik=filing.cik,
            filing_id=filing_id,
            accession_number=filing.accession_number,
            idempotency_key=resolved_key,
            company_name=filing.company_name,
            ticker=filing.ticker,
            form_type=filing.form_type,
            fiscal_year=filing.fiscal_year,
            status="RUNNING",
            current_stage="STARTED",
            db_path=target_db,
            conn=conn,
        )
        record_audit_event(
            event_type="WORKFLOW_STARTED",
            actor="workflow",
            run_id=assigned_run_id,
            cik=filing.cik,
            ticker=filing.ticker,
            company_name=filing.company_name,
            filing_id=filing_id,
            accession_number=filing.accession_number,
            decision="WORKFLOW_STARTED",
            explanation=f"Started {filing.form_type} audit workflow for {filing.ticker or filing.cik} ({filing.accession_number}).",
            payload={
                "cik": filing.cik,
                "ticker": filing.ticker,
                "company_name": filing.company_name,
                "filing_id": filing_id,
                "accession_number": filing.accession_number,
                "fiscal_year": filing.fiscal_year,
                "idempotency_key": resolved_key,
            },
            conn=conn,
        )

    _RUN_INPUT_CACHE[assigned_run_id] = {
        "company_facts": company_facts,
        "html_text": html_text,
        "include_html": include_html,
        "metrics": metrics,
        "segment_items": segment_items,
        "prior_records": prior_records,
        "prior_points": prior_points,
        "confidence_settings": confidence_settings,
        "validation_settings": validation_settings,
    }

    initial_state: WorkflowState = {
        "run_id": assigned_run_id,
        "idempotency_key": resolved_key,
        "cik": filing.cik,
        "ticker": filing.ticker,
        "company_name": filing.company_name,
        "accession_number": filing.accession_number,
        "form_type": filing.form_type,
        "fiscal_year": filing.fiscal_year,
        "filing_dict": filing.model_dump(mode="json"),
        "db_path": str(target_db),
        "extraction_done": False,
        "validation_done": False,
        "auto_approved_metrics": [],
        "escalated_metrics": [],
        "escalation_reasons": {},
        "overall_confidence": None,
        "paused_for_review": False,
        "human_decisions": [],
        "finalized": False,
        "status": "RUNNING",
        "current_stage": "STARTED",
        "executed_nodes": [],
    }

    try:
        with _open_checkpointer(target_db) as saver:
            graph = _compile_workflow_graph(saver)
            result_state = graph.invoke(
                initial_state,
                config={"configurable": {"thread_id": assigned_run_id}},
            )
    except Exception as exc:
        _RUN_INPUT_CACHE.pop(assigned_run_id, None)
        _record_interruption_status(assigned_run_id, exc, target_db)
        raise

    return _outcome_from_result(assigned_run_id, result_state, target_db)


def get_workflow_checkpoint_state(
    run_id: str,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Inspect persisted LangGraph SqliteSaver checkpoint values for a run_id."""
    target_db = resolve_db_path(db_path)
    with _open_checkpointer(target_db) as saver:
        graph = _compile_workflow_graph(saver)
        snapshot = graph.get_state(config={"configurable": {"thread_id": run_id}})
        if snapshot is None or not snapshot.values:
            return None
        return dict(snapshot.values)


def resume_audit_workflow(
    run_id: str,
    *,
    db_path: Path | str | None = None,
) -> WorkflowOutcome:
    """Resume an interrupted or review-paused LangGraph workflow from its SQLite checkpoint."""
    target_db = resolve_db_path(db_path)
    init_db(target_db)

    run_row = fetch_audit_run(run_id, db_path=target_db)
    if run_row is None:
        raise WorkflowError(f"Audit workflow run '{run_id}' was not found in SQLite.")

    with _open_checkpointer(target_db) as saver:
        graph = _compile_workflow_graph(saver)
        snapshot = graph.get_state(config={"configurable": {"thread_id": run_id}})
        if snapshot is None or not snapshot.values:
            raise WorkflowError(f"No LangGraph SQLite checkpoint found for workflow '{run_id}'.")

        existing_state = dict(snapshot.values)

        # Idempotency guard: if already finalized, return persisted state without repeating side effects
        if existing_state.get("finalized") or run_row["status"] in {
            "COMPLETED",
            "COMPLETED_WITH_REJECTIONS",
        }:
            return _outcome_from_result(
                run_id,
                existing_state,
                target_db,
                reused_existing_run=True,
            )

        waiting_at_interrupt = any(bool(task.interrupts) for task in (snapshot.tasks or ())) or (
            snapshot.next == ("human_review",)
        )

        if waiting_at_interrupt:
            remaining_open = fetch_open_review_count_for_run(run_id, db_path=target_db)
            if remaining_open > 0:
                raise WorkflowError(
                    f"Cannot resume workflow '{run_id}': {remaining_open} OPEN review task(s) still require human action."
                )

            resolved_tasks = fetch_review_tasks(run_id=run_id, db_path=target_db, limit=200)
            decision_summary = [
                {
                    "task_id": t["task_id"],
                    "metric_name": t.get("metric_name"),
                    "status": t["status"],
                    "resolved_decimal": t.get("resolved_decimal"),
                    "reviewer_note": t.get("reviewer_note"),
                    "resolved_by": t.get("resolved_by"),
                    "resolved_at": t.get("resolved_at"),
                }
                for t in resolved_tasks
            ]
            resumed_state = graph.invoke(
                Command(resume=decision_summary),
                config={"configurable": {"thread_id": run_id}},
            )
            return _outcome_from_result(run_id, resumed_state, target_db)

        if snapshot.next:
            with get_connection(target_db) as conn:
                update_audit_run_status(
                    run_id=run_id,
                    status="RUNNING",
                    error_message=None,
                    db_path=target_db,
                    conn=conn,
                )
                record_audit_event(
                    event_type="WORKFLOW_RECOVERY_RESUMED",
                    actor="workflow",
                    run_id=run_id,
                    cik=run_row.get("cik"),
                    ticker=run_row.get("ticker"),
                    company_name=run_row.get("company_name"),
                    filing_id=run_row.get("filing_id"),
                    accession_number=run_row.get("accession_number"),
                    decision="WORKFLOW_RECOVERY_RESUMED",
                    explanation=f"Recovered interrupted workflow from stage '{existing_state.get('current_stage')}'.",
                    payload={
                        "resume_from_nodes": list(snapshot.next),
                        "current_stage": existing_state.get("current_stage"),
                    },
                    conn=conn,
                )
            try:
                resumed_state = graph.invoke(
                    None,
                    config={"configurable": {"thread_id": run_id}},
                )
            except Exception as exc:
                _RUN_INPUT_CACHE.pop(run_id, None)
                _record_interruption_status(run_id, exc, target_db)
                raise
            return _outcome_from_result(run_id, resumed_state, target_db)

        return _outcome_from_result(run_id, existing_state, target_db)


def submit_review_decision(
    *,
    task_id: str,
    action: str,
    reviewer_note: str = "",
    corrected_value: Decimal | str | float | int | None = None,
    reviewer: str = "analyst",
    session_id: str | None = None,
    decision_key: str | None = None,
    allow_amendment: bool = False,
    auto_resume: bool = True,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Commit APPROVE/EDIT/REJECT + append-only audit event atomically in one transaction, then resume."""
    target_db = resolve_db_path(db_path)
    init_db(target_db)

    decision = record_human_review_decision(
        task_id=task_id,
        action=action,
        reviewer_note=reviewer_note,
        corrected_value=corrected_value,
        reviewer=reviewer,
        session_id=session_id,
        decision_key=decision_key,
        allow_amendment=allow_amendment,
        db_path=target_db,
    )

    run_id = decision.get("run_id")
    workflow_outcome: WorkflowOutcome | None = None
    if auto_resume and run_id:
        open_left = fetch_open_review_count_for_run(run_id, db_path=target_db)
        if open_left == 0:
            try:
                workflow_outcome = resume_audit_workflow(run_id, db_path=target_db)
            except WorkflowError:
                logger.warning("Review decision saved, but checkpoint resume skipped for run_id=%s", run_id)

    return {
        "decision": decision,
        "remaining_open_for_run": fetch_open_review_count_for_run(run_id, db_path=target_db) if run_id else 0,
        "workflow_outcome": workflow_outcome.model_dump() if workflow_outcome else None,
    }


def submit_subsequent_review_correction(
    *,
    metric_id: int,
    action: str = "EDIT",
    reviewer_note: str = "",
    corrected_value: Decimal | str | float | int | None = None,
    reviewer: str = "analyst",
    session_id: str | None = None,
    decision_key: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Append a subsequent human correction/approval/rejection without altering prior audit records."""
    target_db = resolve_db_path(db_path)
    init_db(target_db)
    decision = amend_metric_review_decision(
        metric_id=metric_id,
        action=action,
        reviewer_note=reviewer_note,
        corrected_value=corrected_value,
        reviewer=reviewer,
        session_id=session_id,
        decision_key=decision_key,
        db_path=target_db,
    )
    run_id = decision.get("run_id")
    return {
        "decision": decision,
        "remaining_open_for_run": fetch_open_review_count_for_run(run_id, db_path=target_db) if run_id else 0,
        "workflow_outcome": None,
    }
