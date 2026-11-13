"""Human review tasks and analyst decision routes."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.auth import AuthUser, require_role
from backend.dependencies import DbPathDep
from backend.schemas import (
    BatchApproveRequest,
    BatchApproveResponse,
    ReviewApproveRequest,
    ReviewCorrectRequest,
    ReviewDecisionResponse,
    ReviewRejectRequest,
    ReviewTaskResponse,
)
from finova_labs.database import fetch_review_tasks
from finova_labs.workflow import submit_review_decision

router = APIRouter(tags=["Human Review & Exceptions"])


def _row_to_review_task(t: dict) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        task_id=t["task_id"],
        run_id=t.get("run_id"),
        cik=t.get("cik"),
        ticker=t.get("ticker"),
        company_name=t.get("company_name"),
        accession_number=t.get("accession_number"),
        metric_id=t.get("metric_id"),
        metric_name=t.get("metric_name"),
        reason=t["reason"],
        status=t["status"],
        raw_value=t.get("raw_value"),
        normalized_decimal=str(t["normalized_decimal"]) if t.get("normalized_decimal") is not None else None,
        unit=t.get("unit", "USD"),
        source_evidence=t.get("source_evidence"),
        evidence_location=t.get("evidence_location"),
        confidence_score=t.get("confidence_score"),
        confidence_threshold=t.get("confidence_threshold"),
        reviewer_note=t.get("reviewer_note"),
        resolved_decimal=str(t["resolved_decimal"]) if t.get("resolved_decimal") is not None else None,
        resolved_by=t.get("resolved_by"),
        created_at=t["created_at"],
        resolved_at=t.get("resolved_at"),
    )


@router.get("/api/reviews", response_model=list[ReviewTaskResponse])
def list_review_tasks(
    db_path: DbPathDep,
    status: str | None = Query(default=None),
    status_filter: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ReviewTaskResponse]:
    """Fetch review tasks flagged for human-in-the-loop analyst sign-off."""
    resolved_status = status or status_filter
    tasks = fetch_review_tasks(
        status=resolved_status.upper() if resolved_status else None,
        run_id=run_id,
        db_path=db_path,
        limit=limit,
    )
    return [_row_to_review_task(t) for t in tasks]


@router.get("/api/reviews/{review_id}", response_model=ReviewTaskResponse)
def get_review_task(review_id: str, db_path: DbPathDep) -> ReviewTaskResponse:
    """Fetch details of a specific review task by ID."""
    tasks = fetch_review_tasks(db_path=db_path, limit=1000)
    target = next((t for t in tasks if t["task_id"] == review_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review task '{review_id}' was not found.",
        )
    return _row_to_review_task(target)


@router.post("/api/reviews/{review_id}/approve", response_model=ReviewDecisionResponse)
def approve_review_task(
    review_id: str,
    payload: ReviewApproveRequest,
    db_path: DbPathDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> ReviewDecisionResponse:
    """Approve the original extracted financial figure as verified."""
    tasks = fetch_review_tasks(db_path=db_path, limit=1000)
    target = next((t for t in tasks if t["task_id"] == review_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review task '{review_id}' was not found.",
        )

    reviewer_ident = payload.reviewer or user.username
    note_val = payload.note or payload.notes or ""
    res = submit_review_decision(
        task_id=review_id,
        action="APPROVE",
        reviewer_note=note_val,
        reviewer=reviewer_ident,
        auto_resume=payload.auto_resume,
        db_path=db_path,
    )

    wf_res = res.get("workflow_outcome") or {}
    return ReviewDecisionResponse(
        task_id=review_id,
        action="APPROVE",
        decision_saved=True,
        remaining_open_tasks=res.get("remaining_open_for_run", 0),
        resumed_workflow_status=wf_res.get("status"),
        resumed_run_id=wf_res.get("run_id"),
    )


@router.post("/api/reviews/{review_id}/correct", response_model=ReviewDecisionResponse)
def correct_review_task(
    review_id: str,
    payload: ReviewCorrectRequest,
    db_path: DbPathDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> ReviewDecisionResponse:
    """Apply a corrected figure with required audit justification note."""
    tasks = fetch_review_tasks(db_path=db_path, limit=1000)
    target = next((t for t in tasks if t["task_id"] == review_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review task '{review_id}' was not found.",
        )

    note_val = (payload.note or payload.notes or "").strip()
    if not note_val:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An audit justification note is mandatory when correcting a financial value.",
        )

    reviewer_ident = payload.reviewer or user.username
    res = submit_review_decision(
        task_id=review_id,
        action="EDIT",
        corrected_value=payload.corrected_value,
        reviewer_note=note_val,
        reviewer=reviewer_ident,
        auto_resume=payload.auto_resume,
        db_path=db_path,
    )

    wf_res = res.get("workflow_outcome") or {}
    return ReviewDecisionResponse(
        task_id=review_id,
        action="EDIT",
        decision_saved=True,
        remaining_open_tasks=res.get("remaining_open_for_run", 0),
        resumed_workflow_status=wf_res.get("status"),
        resumed_run_id=wf_res.get("run_id"),
    )


@router.post("/api/reviews/{review_id}/reject", response_model=ReviewDecisionResponse)
def reject_review_task(
    review_id: str,
    payload: ReviewRejectRequest,
    db_path: DbPathDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> ReviewDecisionResponse:
    """Reject an extracted financial figure with required audit justification note."""
    tasks = fetch_review_tasks(db_path=db_path, limit=1000)
    target = next((t for t in tasks if t["task_id"] == review_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review task '{review_id}' was not found.",
        )

    if not payload.note.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An audit justification note is mandatory when rejecting a financial value.",
        )

    reviewer_ident = payload.reviewer or user.username
    res = submit_review_decision(
        task_id=review_id,
        action="REJECT",
        reviewer_note=payload.note,
        reviewer=reviewer_ident,
        auto_resume=payload.auto_resume,
        db_path=db_path,
    )

    wf_res = res.get("workflow_outcome") or {}
    return ReviewDecisionResponse(
        task_id=review_id,
        action="REJECT",
        decision_saved=True,
        remaining_open_tasks=res.get("remaining_open_for_run", 0),
        resumed_workflow_status=wf_res.get("status"),
        resumed_run_id=wf_res.get("run_id"),
    )


@router.post("/api/reviews/batch-approve", response_model=BatchApproveResponse)
def batch_approve_review_tasks(
    payload: BatchApproveRequest,
    db_path: DbPathDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> BatchApproveResponse:
    """Approve multiple review tasks with a shared audit note."""
    reviewer_ident = payload.reviewer or user.username
    note_val = payload.note or payload.notes or "Batch approved by analyst."
    approved_count = 0
    failed_count = 0
    last_res = {}

    for idx, t_id in enumerate(payload.task_ids):
        # Only auto-resume on the very last task of the batch
        is_last = (idx == len(payload.task_ids) - 1)
        try:
            last_res = submit_review_decision(
                task_id=t_id,
                action="APPROVE",
                reviewer_note=note_val,
                reviewer=reviewer_ident,
                auto_resume=payload.auto_resume if is_last else False,
                db_path=db_path,
            )
            approved_count += 1
        except Exception:
            failed_count += 1

    wf_res = last_res.get("workflow_outcome") or {}
    return BatchApproveResponse(
        approved_count=approved_count,
        failed_count=failed_count,
        remaining_open_tasks=last_res.get("remaining_open_for_run", 0),
        resumed_workflow_status=wf_res.get("status"),
        resumed_run_id=wf_res.get("run_id"),
    )


