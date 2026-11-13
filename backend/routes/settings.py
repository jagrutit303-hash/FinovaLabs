"""Settings and configuration management routes."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.auth import AuthUser, require_role
from backend.dependencies import SettingsDep
from finova_labs.settings import ConfidenceSettings, ConfidenceWeights, ValidationSettings

router = APIRouter(tags=["Settings & Configuration"])


class SettingsResponse(BaseModel):
    app_name: str
    version: str
    auto_approve_threshold: float
    review_required_threshold: float
    accounting_identity_tolerance: float
    segment_reconciliation_tolerance: float
    yoy_change_alert_threshold: float
    confidence_weights: dict[str, float]
    sec_cache_dir: str
    sec_user_agent: str
    db_path: str


class SettingsUpdateRequest(BaseModel):
    auto_approve_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    review_required_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    accounting_identity_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    segment_reconciliation_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    yoy_change_alert_threshold: float | None = Field(default=None, ge=0.0, le=10.0)


@router.get("/api/settings", response_model=SettingsResponse)
def get_settings_endpoint(settings: SettingsDep) -> SettingsResponse:
    """Return active confidence thresholds, validation tolerances, and environment settings."""
    cw = settings.confidence.weights
    weights = {
        "label_concept_match": cw.label_concept_match,
        "reporting_period_match": cw.reporting_period_match,
        "unit_scale_correctness": cw.unit_scale_correctness,
        "evidence_quality": cw.evidence_quality,
        "independent_path_agreement": cw.independent_path_agreement,
    }
    return SettingsResponse(
        app_name=settings.app.name,
        version=settings.confidence.scoring_version,
        auto_approve_threshold=settings.confidence.auto_approve_threshold,
        review_required_threshold=settings.confidence.review_required_threshold,
        accounting_identity_tolerance=settings.validation.accounting_identity_tolerance,
        segment_reconciliation_tolerance=settings.validation.segment_reconciliation_tolerance,
        yoy_change_alert_threshold=settings.validation.yoy_change_alert_threshold,
        confidence_weights=weights,
        sec_cache_dir=str(settings.cache_path),
        sec_user_agent=settings.sec.user_agent,
        db_path=str(settings.db_file),
    )


@router.put("/api/settings", response_model=SettingsResponse)
@router.post("/api/settings", response_model=SettingsResponse)
def update_settings_endpoint(
    payload: SettingsUpdateRequest,
    settings: SettingsDep,
    user: Annotated[AuthUser, Depends(require_role(["admin", "analyst"]))],
) -> SettingsResponse:
    """Update active confidence and validation thresholds in-memory for the current runtime."""
    if payload.auto_approve_threshold is not None:
        settings.confidence.auto_approve_threshold = payload.auto_approve_threshold
    if payload.review_required_threshold is not None:
        settings.confidence.review_required_threshold = payload.review_required_threshold
    if payload.accounting_identity_tolerance is not None:
        settings.validation.accounting_identity_tolerance = payload.accounting_identity_tolerance
    if payload.segment_reconciliation_tolerance is not None:
        settings.validation.segment_reconciliation_tolerance = payload.segment_reconciliation_tolerance
    if payload.yoy_change_alert_threshold is not None:
        settings.validation.yoy_change_alert_threshold = payload.yoy_change_alert_threshold

    return get_settings_endpoint(settings)

