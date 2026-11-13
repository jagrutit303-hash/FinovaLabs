"""Health and dashboard summary routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.dependencies import DbPathDep
from backend.schemas import DashboardSummaryResponse, HealthResponse
from finova_labs.database import check_db_health, fetch_dashboard_summary

router = APIRouter(tags=["Health & Dashboard"])


@router.get("/api/health", response_model=HealthResponse)
def get_health(db_path: DbPathDep) -> HealthResponse:
    """Return database health, table counts, and application version."""
    health = check_db_health(db_path=db_path)
    return HealthResponse(
        status="healthy" if health.get("healthy") else "degraded",
        healthy=bool(health.get("healthy")),
        sqlite_version=health.get("sqlite_version"),
        table_counts=health.get("table_counts", {}),
        missing_tables=health.get("missing_tables", []),
        db_path=str(health.get("db_path") or db_path),
        version="1.0.0",
    )


@router.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(db_path: DbPathDep) -> DashboardSummaryResponse:
    """Return operational audit counts calculated directly from SQLite records."""
    summary = fetch_dashboard_summary(db_path=db_path)
    return DashboardSummaryResponse(
        total_runs=summary.get("total_runs", 0),
        total_filings=summary.get("total_filings", 0),
        open_reviews=summary.get("open_reviews", 0),
        resolved_reviews=summary.get("resolved_reviews", 0),
        failed_validations=summary.get("failed_validations", 0),
        audit_events=summary.get("audit_events", 0),
    )

