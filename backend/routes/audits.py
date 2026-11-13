"""Audit runs, extraction results, validations, reports, and history routes."""

from __future__ import annotations

from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.auth import AuthUser, require_role
from backend.dependencies import DbPathDep, SettingsDep
from backend.schemas import (
    AccuracyReportResponse,
    AuditChainVerificationResponse,
    AuditCreateRequest,
    AuditEventResponse,
    AuditRunResponse,
    EvidenceResponse,
    ExtractedMetricResponse,
    ValidationResultResponse,
)
from finova_labs.database import (
    fetch_accuracy_evaluations,
    fetch_audit_events,
    fetch_audit_run,
    fetch_extracted_metrics,
    fetch_filing_metadata,
    fetch_open_review_count_for_run,
    fetch_runs,
    fetch_validation_results,
    get_connection,
)
from finova_labs.evaluation import evaluate_run_against_company_facts
from finova_labs.extractor import FilingMetadata
from finova_labs.sec_client import SecEdgarClient, normalize_cik
from finova_labs.settings import ConfidenceSettings
from finova_labs.workflow import (
    resume_audit_workflow,
    start_audit_workflow,
)

router = APIRouter(tags=["Audits & Compliance"])


def _row_to_audit_response(r: dict[str, Any], db_path: Any) -> AuditRunResponse:
    open_tasks = fetch_open_review_count_for_run(r["run_id"], db_path=db_path)
    return AuditRunResponse(
        run_id=r["run_id"],
        cik=r["cik"],
        ticker=r.get("ticker"),
        company_name=r.get("company_name"),
        accession_number=r.get("accession_number"),
        form_type=r.get("form_type", "10-K"),
        fiscal_year=r.get("fiscal_year"),
        status=r["status"],
        current_stage=r.get("current_stage", "STARTED"),
        overall_confidence=r.get("overall_confidence"),
        paused=r["status"] == "PAUSED_FOR_REVIEW" or open_tasks > 0,
        open_review_tasks=open_tasks,
        idempotency_key=r.get("idempotency_key"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
        error_message=r.get("error_message"),
    )


@router.post("/api/audits", response_model=AuditRunResponse, status_code=status.HTTP_201_CREATED)
def create_audit(
    payload: AuditCreateRequest,
    db_path: DbPathDep,
    settings: SettingsDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> AuditRunResponse:
    """Start or idempotently recover a LangGraph audit run for a company filing."""
    target_cik = None
    if payload.cik:
        target_cik = normalize_cik(payload.cik)
    elif payload.ticker:
        from backend.routes.companies import KNOWN_CIKS
        target_cik = KNOWN_CIKS.get(payload.ticker.upper())
        if not target_cik:
            client = SecEdgarClient(settings=settings)
            target_cik = client.lookup_company_by_ticker(payload.ticker).cik

    if not target_cik:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either a valid company ticker or CIK must be provided.",
        )

    # Locate the matching SEC filing in the database
    filings = fetch_filing_metadata(cik=target_cik, db_path=db_path)
    target_filing_row = None

    if payload.accession_number:
        for f in filings:
            if f["accession_number"] == payload.accession_number:
                target_filing_row = f
                break
    elif filings:
        target_filing_row = filings[0]

    if not target_filing_row:
        # If not ingested yet, pull latest 10-K from SEC EDGAR
        client = SecEdgarClient(settings=settings)
        ticker_val = payload.ticker or "AAPL"
        try:
            bundle = client.fetch_latest_10k_bundle(ticker_val, persist=True, db_path=db_path)
            filing_obj = bundle.latest_10k
            company_facts = bundle.company_facts.facts
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to retrieve SEC Form 10-K for {ticker_val}: {exc}",
            )
    else:
        filing_obj = FilingMetadata(
            cik=target_filing_row["cik"],
            ticker=target_filing_row.get("ticker"),
            company_name=target_filing_row.get("company_name"),
            accession_number=target_filing_row["accession_number"],
            form_type=target_filing_row["form_type"],
            filing_date=target_filing_row["filing_date"],
            reporting_period=target_filing_row.get("reporting_period"),
            fiscal_year=target_filing_row.get("fiscal_year"),
            primary_document=target_filing_row.get("primary_document"),
            filing_url=target_filing_row["filing_url"],
            submissions_url=target_filing_row["submissions_url"],
            companyfacts_url=target_filing_row["companyfacts_url"],
        )
        client = SecEdgarClient(settings=settings)
        try:
            company_facts = client.get_company_facts(target_filing_row["cik"]).facts
        except Exception:
            company_facts = None

    conf_settings = None
    if payload.auto_approve_threshold is not None:
        conf_settings = ConfidenceSettings(
            auto_approve_threshold=payload.auto_approve_threshold,
            scoring_version=settings.confidence.scoring_version,
            weights=settings.confidence.weights,
        )

    try:
        outcome = start_audit_workflow(
            filing=filing_obj,
            company_facts=company_facts,
            force_new_run=payload.force_reprocess,
            confidence_settings=conf_settings,
            db_path=db_path,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution halted: {exc}",
        )

    run_row = fetch_audit_run(outcome.run_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load newly created audit run record from SQLite.",
        )

    resp = _row_to_audit_response(run_row, db_path=db_path)
    resp.reused_existing_run = outcome.reused_existing_run
    return resp


@router.get("/api/audits", response_model=list[AuditRunResponse])
def list_audits(
    db_path: DbPathDep,
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[AuditRunResponse]:
    """List recent financial audit runs with compliance status and confidence."""
    runs = fetch_runs(limit=limit, db_path=db_path)
    if status_filter:
        runs = [r for r in runs if r["status"].upper() == status_filter.upper()]
    return [_row_to_audit_response(r, db_path) for r in runs]


@router.get("/api/audits/{audit_id}", response_model=AuditRunResponse)
def get_audit(audit_id: str, db_path: DbPathDep) -> AuditRunResponse:
    """Fetch details for a specific audit run by ID."""
    run_row = fetch_audit_run(audit_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found.",
        )
    return _row_to_audit_response(run_row, db_path)


@router.get("/api/audits/{audit_id}/results", response_model=list[ExtractedMetricResponse])
def get_audit_results(audit_id: str, db_path: DbPathDep) -> list[ExtractedMetricResponse]:
    """Fetch the 8 standardized financial metrics extracted for this audit run."""
    run_row = fetch_audit_run(audit_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found.",
        )
    metrics = fetch_extracted_metrics(run_id=audit_id, db_path=db_path)
    return [
        ExtractedMetricResponse(
            id=m.get("id"),
            run_id=m.get("run_id"),
            metric_name=m["metric_name"],
            xbrl_concept=m.get("xbrl_concept"),
            raw_value=m.get("raw_value"),
            normalized_value=m.get("normalized_value"),
            normalized_decimal=m.get("normalized_decimal"),
            unit=m.get("unit", "USD"),
            currency=m.get("currency", "USD"),
            scale_factor=m.get("scale_factor", 1),
            fiscal_period=m.get("fiscal_period", "FY"),
            fiscal_year=m.get("fiscal_year"),
            period_start=m.get("period_start"),
            period_end=m.get("period_end"),
            source_url=m.get("source_url"),
            source_evidence=m.get("source_evidence"),
            evidence_location=m.get("evidence_location"),
            extraction_status=m.get("extraction_status", "EXTRACTED"),
            confidence_score=m.get("confidence_score"),
            confidence_threshold=m.get("confidence_threshold"),
            scoring_version=m.get("scoring_version"),
            validation_status=m.get("validation_status", "PENDING"),
            review_status=m.get("review_status", "NOT_REQUIRED"),
            reviewed_decimal=m.get("reviewed_decimal"),
            created_at=m.get("created_at"),
        )
        for m in metrics
    ]


@router.get("/api/audits/{audit_id}/validations", response_model=list[ValidationResultResponse])
def get_audit_validations(audit_id: str, db_path: DbPathDep) -> list[ValidationResultResponse]:
    """Fetch accounting equation, segment, and YoY validation results."""
    run_row = fetch_audit_run(audit_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found.",
        )
    vals = fetch_validation_results(accession_number=run_row.get("accession_number"), db_path=db_path)
    return [
        ValidationResultResponse(
            validation_id=v["validation_id"],
            run_id=v.get("run_id") or audit_id,
            cik=v.get("cik"),
            ticker=v.get("ticker"),
            accession_number=v.get("accession_number"),
            rule_name=v["rule_name"],
            metric_name=v["metric_name"],
            status=v["status"],
            explanation=v["explanation"],
            expected_value=v.get("expected_value"),
            actual_value=v.get("actual_value"),
            variance_abs=v.get("variance_abs"),
            variance_pct=v.get("variance_pct"),
            tolerance_used=v.get("tolerance_used"),
            escalated=bool(v.get("escalated")),
            evaluated_at=v.get("evaluated_at"),
        )
        for v in vals
    ]


@router.get("/api/audits/{audit_id}/evidence", response_model=list[EvidenceResponse])
def get_audit_evidence(audit_id: str, db_path: DbPathDep) -> list[EvidenceResponse]:
    """Fetch verbatim 10-K evidence snippets, table locations, and SEC URLs."""
    metrics = fetch_extracted_metrics(run_id=audit_id, db_path=db_path)
    if not metrics:
        run_row = fetch_audit_run(audit_id, db_path=db_path)
        if not run_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Audit run '{audit_id}' was not found.",
            )
    return [
        EvidenceResponse(
            metric_name=m["metric_name"],
            raw_value=m.get("raw_value"),
            normalized_decimal=m.get("normalized_decimal"),
            unit=m.get("unit", "USD"),
            source_evidence=m.get("source_evidence"),
            evidence_location=m.get("evidence_location"),
            source_url=m.get("source_url"),
            extraction_status=m.get("extraction_status", "EXTRACTED"),
        )
        for m in metrics
    ]


@router.post("/api/audits/{audit_id}/resume", response_model=AuditRunResponse)
def resume_audit(
    audit_id: str,
    db_path: DbPathDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> AuditRunResponse:
    """Resume an interrupted or review-paused workflow from its SQLite checkpoint."""
    run_row = fetch_audit_run(audit_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found.",
        )
    try:
        outcome = resume_audit_workflow(audit_id, db_path=db_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume audit '{audit_id}': {exc}",
        )
    updated_row = fetch_audit_run(audit_id, db_path=db_path)
    return _row_to_audit_response(updated_row or run_row, db_path)


@router.get("/api/audits/{audit_id}/report", response_model=AccuracyReportResponse)
def get_audit_report(audit_id: str, db_path: DbPathDep) -> AccuracyReportResponse:
    """Generate or retrieve pre/post review SEC Company Facts accuracy benchmarking."""
    run_row = fetch_audit_run(audit_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found.",
        )

    evals = fetch_accuracy_evaluations(run_id=audit_id, db_path=db_path)
    if not evals:
        # Evaluate on demand against cached SEC facts
        try:
            eval_result = evaluate_run_against_company_facts(audit_id, persist=True, db_path=db_path)
            evals = fetch_accuracy_evaluations(run_id=audit_id, db_path=db_path)
        except Exception as exc:
            pass

    evaluated_count = len(evals)
    matched_count = sum(1 for e in evals if bool(e.get("matched") or e.get("post_exact_match")))
    pre_exact = sum(1 for e in evals if bool(e.get("pre_exact_match")))

    pre_acc = round(pre_exact / evaluated_count, 4) if evaluated_count else 0.0
    post_acc = round(matched_count / evaluated_count, 4) if evaluated_count else 0.0

    enriched_evals = []
    for e in evals:
        item = dict(e)
        ref_val = e.get("reference_value") or e.get("ground_truth_decimal") or e.get("ground_truth_value")
        ext_val = e.get("extracted_value") or e.get("post_review_decimal") or e.get("pre_review_decimal")
        cpt = e.get("concept") or e.get("xbrl_concept") or e.get("ground_truth_concept")
        item["reference_value"] = str(ref_val) if ref_val is not None else None
        item["extracted_value"] = str(ext_val) if ext_val is not None else None
        item["concept"] = cpt
        enriched_evals.append(item)

    return AccuracyReportResponse(
        run_id=audit_id,
        ticker=run_row.get("ticker"),
        company_name=run_row.get("company_name"),
        accession_number=run_row.get("accession_number"),
        pre_review_accuracy=pre_acc,
        post_review_accuracy=post_acc,
        evaluated_metrics_count=evaluated_count,
        matched_metrics_count=matched_count,
        coverage_denominator=evaluated_count or 8,
        evaluations=enriched_evals,
    )


@router.get("/api/audits/{audit_id}/history", response_model=list[AuditEventResponse])
def get_audit_history(audit_id: str, db_path: DbPathDep) -> list[AuditEventResponse]:
    """Fetch cryptographic SHA-256 audit events recorded for this audit run."""
    run_row = fetch_audit_run(audit_id, db_path=db_path)
    if not run_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{audit_id}' was not found.",
        )
    events = fetch_audit_events(run_id=audit_id, db_path=db_path, limit=200)
    return [
        AuditEventResponse(
            event_id=ev["event_id"],
            seq_id=ev.get("seq_id"),
            run_id=ev.get("run_id"),
            ticker=ev.get("ticker"),
            company_name=ev.get("company_name"),
            metric_name=ev.get("metric_name"),
            event_type=ev["event_type"],
            decision=ev.get("decision"),
            original_value=ev.get("original_value"),
            corrected_value=ev.get("corrected_value"),
            actor=ev.get("actor", "system"),
            reviewer_id=ev.get("reviewer_id"),
            explanation=ev.get("explanation"),
            prev_hash=ev["prev_hash"],
            event_hash=ev["event_hash"],
            created_at=ev["created_at"],
        )
        for ev in events
    ]


@router.get("/api/audits/{audit_id}/verify-chain", response_model=AuditChainVerificationResponse)
@router.get("/api/audit-trail/verify", response_model=AuditChainVerificationResponse)
def verify_audit_trail_chain(db_path: DbPathDep) -> AuditChainVerificationResponse:
    """Cryptographically verify the SHA-256 hash chaining of the audit event ledger."""
    from finova_labs.audit import verify_audit_chain
    chain_valid, total_events, reason = verify_audit_chain(db_path=db_path)
    return AuditChainVerificationResponse(
        chain_valid=chain_valid,
        total_events=total_events,
        reason=reason,
    )

