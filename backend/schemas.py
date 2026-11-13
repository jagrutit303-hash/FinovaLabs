"""Pydantic schemas for FinovaLabs FastAPI request and response validation."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    healthy: bool
    sqlite_version: str | None = None
    table_counts: dict[str, int] = Field(default_factory=dict)
    missing_tables: list[str] = Field(default_factory=list)
    db_path: str
    version: str = "1.0.0"


class DashboardSummaryResponse(BaseModel):
    total_runs: int
    total_filings: int
    open_reviews: int
    resolved_reviews: int
    failed_validations: int
    audit_events: int


class CompanyResponse(BaseModel):
    company_id: str
    ticker: str
    cik: str | None = None
    company_name: str
    display_name: str


class FilingResponse(BaseModel):
    id: int | None = None
    cik: str
    ticker: str | None = None
    company_name: str | None = None
    accession_number: str
    form_type: str
    filing_date: str
    reporting_period: str | None = None
    fiscal_year: int | None = None
    retrieval_status: str
    filing_url: str | None = None
    fetched_at: str | None = None


class AuditCreateRequest(BaseModel):
    ticker: str | None = None
    cik: str | None = None
    accession_number: str | None = None
    force_reprocess: bool = False
    auto_approve_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class AuditRunResponse(BaseModel):
    run_id: str
    cik: str
    ticker: str | None = None
    company_name: str | None = None
    accession_number: str | None = None
    form_type: str = "10-K"
    fiscal_year: int | None = None
    status: str
    current_stage: str
    overall_confidence: float | None = None
    paused: bool = False
    open_review_tasks: int = 0
    reused_existing_run: bool = False
    idempotency_key: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    error_message: str | None = None


class ExtractedMetricResponse(BaseModel):
    id: int | None = None
    run_id: str | None = None
    metric_name: str
    xbrl_concept: str | None = None
    raw_value: str | None = None
    normalized_value: float | None = None
    normalized_decimal: str | None = None
    unit: str | None = "USD"
    currency: str | None = "USD"
    scale_factor: int | None = 1
    fiscal_period: str | None = "FY"
    fiscal_year: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    source_url: str | None = None
    source_evidence: str | None = None
    evidence_location: str | None = None
    extraction_status: str = "EXTRACTED"
    confidence_score: float | None = None
    confidence_threshold: float | None = None
    scoring_version: str | None = None
    validation_status: str | None = "PENDING"
    review_status: str | None = "NOT_REQUIRED"
    reviewed_decimal: str | None = None
    created_at: str | None = None


class ValidationResultResponse(BaseModel):
    validation_id: str
    run_id: str | None = None
    cik: str | None = None
    ticker: str | None = None
    accession_number: str | None = None
    rule_name: str
    metric_name: str
    status: str
    explanation: str
    expected_value: str | None = None
    actual_value: str | None = None
    variance_abs: str | None = None
    variance_pct: str | None = None
    tolerance_used: str | None = None
    escalated: bool = False
    evaluated_at: str | None = None


class EvidenceResponse(BaseModel):
    metric_name: str
    raw_value: str | None = None
    normalized_decimal: str | None = None
    unit: str | None = "USD"
    source_evidence: str | None = None
    evidence_location: str | None = None
    source_url: str | None = None
    extraction_status: str = "EXTRACTED"


class ReviewTaskResponse(BaseModel):
    task_id: str
    run_id: str | None = None
    cik: str | None = None
    ticker: str | None = None
    company_name: str | None = None
    accession_number: str | None = None
    metric_id: int | None = None
    metric_name: str | None = None
    reason: str
    status: str
    raw_value: str | None = None
    normalized_decimal: str | None = None
    unit: str | None = "USD"
    source_evidence: str | None = None
    evidence_location: str | None = None
    confidence_score: float | None = None
    confidence_threshold: float | None = None
    reviewer_note: str | None = None
    resolved_decimal: str | None = None
    resolved_by: str | None = None
    created_at: str
    resolved_at: str | None = None


class ReviewApproveRequest(BaseModel):
    reviewer: str = "analyst"
    note: str = ""
    notes: str | None = None
    auto_resume: bool = True


class ReviewCorrectRequest(BaseModel):
    corrected_value: str = Field(min_length=1, description="Standardized corrected decimal amount")
    reviewer: str = "analyst"
    note: str | None = None
    notes: str | None = None
    auto_resume: bool = True


class ReviewRejectRequest(BaseModel):
    reviewer: str = "analyst"
    note: str | None = None
    notes: str | None = None
    reason: str | None = None
    auto_resume: bool = True


class ReviewDecisionResponse(BaseModel):
    task_id: str
    action: str
    decision_saved: bool
    remaining_open_tasks: int
    resumed_workflow_status: str | None = None
    resumed_run_id: str | None = None


class BatchApproveRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, description="List of review task IDs to approve")
    reviewer: str = "analyst"
    note: str = ""
    notes: str | None = None
    auto_resume: bool = True


class BatchApproveResponse(BaseModel):
    approved_count: int
    failed_count: int = 0
    remaining_open_tasks: int = 0
    resumed_workflow_status: str | None = None
    resumed_run_id: str | None = None


class AccuracyReportResponse(BaseModel):
    run_id: str
    ticker: str | None = None
    company_name: str | None = None
    accession_number: str | None = None
    pre_review_accuracy: float
    post_review_accuracy: float
    evaluated_metrics_count: int
    matched_metrics_count: int
    coverage_denominator: int
    evaluations: list[dict[str, Any]] = Field(default_factory=list)


class AuditEventResponse(BaseModel):
    event_id: int
    seq_id: int | None = None
    run_id: str | None = None
    ticker: str | None = None
    company_name: str | None = None
    metric_name: str | None = None
    event_type: str
    decision: str | None = None
    original_value: str | None = None
    corrected_value: str | None = None
    actor: str = "system"
    reviewer_id: str | None = None
    explanation: str | None = None
    prev_hash: str
    event_hash: str
    created_at: str


class AuditChainVerificationResponse(BaseModel):
    chain_valid: bool
    total_events: int
    reason: str | None = None

