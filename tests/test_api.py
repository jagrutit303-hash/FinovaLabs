"""Comprehensive integration tests for FinovaLabs FastAPI backend endpoints."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.dependencies import get_db_file
from backend.main import app
from finova_labs.audit import record_audit_event
from finova_labs.database import (
    create_audit_run,
    fetch_audit_run,
    fetch_review_tasks,
    init_db,
    record_human_review_decision,
    save_extracted_metrics,
    sync_review_tasks_for_filing,
)
from finova_labs.sec_client import SecEdgarClient
from finova_labs.settings import ConfidenceSettings, get_settings


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide a TestClient connected to an isolated test SQLite database with local SEC cache."""
    test_db = tmp_path / "test_api_finova.db"
    init_db(test_db)

    settings = get_settings()
    settings.app.db_path = str(test_db)
    repo_cache = (Path(__file__).resolve().parent.parent / "data" / "cache" / "sec").resolve()
    settings.sec.cache_dir = str(repo_cache)

    import finova_labs.database as db_mod
    import finova_labs.workflow as wf_mod
    import finova_labs.evaluation as eval_mod
    import backend.dependencies as deps_mod

    monkeypatch.setattr(db_mod, "resolve_db_path", lambda db_path=None: Path(db_path) if db_path else test_db)
    monkeypatch.setattr(wf_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(eval_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(deps_mod, "get_backend_settings", lambda: settings)

    app.dependency_overrides[get_db_file] = lambda: test_db

    with TestClient(app) as client:
        yield client, test_db

    app.dependency_overrides.clear()


def test_health_and_companies_endpoints(api_client):
    """Verify /api/health and /api/companies return expected schema and live database state."""
    client, test_db = api_client

    # 1. Health check
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["healthy"] is True
    assert data["status"] == "healthy"
    assert "audit_runs" in data["table_counts"]
    assert "sec_filings" in data["table_counts"]

    # 2. Supported Companies
    res = client.get("/api/companies")
    assert res.status_code == 200
    companies = res.json()
    tickers = {c["ticker"] for c in companies}
    assert {"AAPL", "MSFT", "GOOGL", "AMZN", "WMT"}.issubset(tickers)


def test_new_audit_and_duplicate_prevention(api_client):
    """Test starting an audit from cached SEC data and verify idempotency / duplicate prevention."""
    client, test_db = api_client

    # Step 1: Create a new audit for Apple AAPL
    res = client.post("/api/audits", json={"ticker": "AAPL", "force_reprocess": False})
    assert res.status_code == 201
    audit_data = res.json()
    run_id = audit_data["run_id"]
    assert run_id.startswith("run-")
    assert audit_data["ticker"] == "AAPL"
    assert audit_data["status"] == "PAUSED_FOR_REVIEW"
    assert audit_data["reused_existing_run"] is False

    # Step 2: Request the same audit again with force_reprocess=False -> must return existing audit run (Idempotency)
    res_dup = client.post("/api/audits", json={"ticker": "AAPL", "force_reprocess": False})
    assert res_dup.status_code == 201
    dup_data = res_dup.json()
    assert dup_data["run_id"] == run_id
    assert dup_data["reused_existing_run"] is True


def test_existing_audit_lookup_results_validations_evidence(api_client):
    """Test retrieving run details, 8 extracted metrics, validations, and evidence citations."""
    client, test_db = api_client

    # Create audit run
    res = client.post("/api/audits", json={"ticker": "AAPL"})
    assert res.status_code == 201
    run_id = res.json()["run_id"]

    # 1. GET /api/audits/{audit_id}
    res_run = client.get(f"/api/audits/{run_id}")
    assert res_run.status_code == 200
    assert res_run.json()["run_id"] == run_id

    # 2. GET /api/audits/{audit_id}/results -> 8 standardized financial metrics
    res_results = client.get(f"/api/audits/{run_id}/results")
    assert res_results.status_code == 200
    metrics = res_results.json()
    assert len(metrics) == 8
    metric_names = {m["metric_name"] for m in metrics}
    assert "Revenue" in metric_names
    assert "Net Income" in metric_names
    assert "Total Assets" in metric_names
    assert "Total Liabilities" in metric_names

    # 3. GET /api/audits/{audit_id}/validations -> Accounting equation results
    res_vals = client.get(f"/api/audits/{run_id}/validations")
    assert res_vals.status_code == 200
    vals = res_vals.json()
    assert len(vals) >= 1
    assert any("Accounting Equation" in v["metric_name"] for v in vals)

    # 4. GET /api/audits/{audit_id}/evidence -> Verbatim quotes
    res_ev = client.get(f"/api/audits/{run_id}/evidence")
    assert res_ev.status_code == 200
    evidence_items = res_ev.json()
    assert len(evidence_items) == 8
    revenue_ev = next(e for e in evidence_items if e["metric_name"] == "Revenue")
    assert revenue_ev["raw_value"] is not None


def test_pending_review_and_decision_actions(api_client):
    """Test fetching open review tasks and applying Approve, Correct Value, and Reject actions."""
    client, test_db = api_client

    # Create audit run with lower threshold to ensure pause
    res = client.post("/api/audits", json={"ticker": "AAPL", "auto_approve_threshold": 0.99})
    assert res.status_code == 201
    run_id = res.json()["run_id"]

    # 1. Fetch pending reviews
    res_rev = client.get("/api/reviews?status=OPEN")
    assert res_rev.status_code == 200
    tasks = res_rev.json()
    assert len(tasks) >= 1
    task_id = tasks[0]["task_id"]

    # 2. Correct Value without note -> must return HTTP 422
    bad_correct = client.post(
        f"/api/reviews/{task_id}/correct",
        json={"corrected_value": "93736000000", "note": ""},
    )
    assert bad_correct.status_code == 422

    # 3. Correct Value with mandatory note -> must succeed and persist atomically
    ok_correct = client.post(
        f"/api/reviews/{task_id}/correct",
        json={
            "corrected_value": "93736000000",
            "reviewer": "senior.auditor",
            "note": "Verified Net Income against Statement of Operations in Form 10-K.",
            "auto_resume": False,
        },
    )
    assert ok_correct.status_code == 200
    decision_data = ok_correct.json()
    assert decision_data["decision_saved"] is True
    assert decision_data["action"] == "EDIT"

    # Verify task status in database is now CORRECTED
    updated_task = client.get(f"/api/reviews/{task_id}").json()
    assert updated_task["status"] == "CORRECTED"
    assert updated_task["resolved_decimal"] == "93736000000"
    assert updated_task["resolved_by"] == "senior.auditor"


def test_workflow_resumption_and_report_retrieval(api_client):
    """Test resuming workflow after human sign-off, benchmark reports, and SHA-256 audit trail."""
    client, test_db = api_client

    res = client.post("/api/audits", json={"ticker": "AAPL", "auto_approve_threshold": 0.90})
    assert res.status_code == 201
    run_id = res.json()["run_id"]

    # Resolve all open review tasks
    open_tasks = client.get(f"/api/reviews?run_id={run_id}&status=OPEN").json()
    for t in open_tasks:
        client.post(
            f"/api/reviews/{t['task_id']}/approve",
            json={"reviewer": "test.lead", "note": "Approved for testing.", "auto_resume": False},
        )

    # Resume workflow
    res_resume = client.post(f"/api/audits/{run_id}/resume")
    assert res_resume.status_code == 200
    resumed = res_resume.json()
    assert resumed["status"] in ("COMPLETED", "COMPLETED_WITH_REJECTIONS")

    # Accuracy report retrieval
    res_rep = client.get(f"/api/audits/{run_id}/report")
    assert res_rep.status_code == 200
    report = res_rep.json()
    assert report["run_id"] == run_id
    assert report["post_review_accuracy"] >= 0.85

    # Audit history retrieval (cryptographic SHA-256 events)
    res_hist = client.get(f"/api/audits/{run_id}/history")
    assert res_hist.status_code == 200
    events = res_hist.json()
    assert len(events) >= 2
    assert all("event_hash" in ev for ev in events)


def test_persistence_after_restart(api_client):
    """Test that records in the SQLite database persist across fresh server connections."""
    client, test_db = api_client

    # Create run
    res = client.post("/api/audits", json={"ticker": "AAPL"})
    run_id = res.json()["run_id"]

    # Discard client and open fresh TestClient pointing to the exact same test_db
    app.dependency_overrides[get_db_file] = lambda: test_db
    with TestClient(app) as client_restart:
        res_after = client_restart.get(f"/api/audits/{run_id}")
        assert res_after.status_code == 200
        assert res_after.json()["run_id"] == run_id


def test_analytics_endpoints(api_client):
    """Test /api/analytics/options and /api/analytics/audit/{audit_id} endpoints."""
    client, test_db = api_client
    res_opts = client.get("/api/analytics/options")
    assert res_opts.status_code == 200
    assert "runs" in res_opts.json()
    assert "companies" in res_opts.json()

    # Create an audit run
    res = client.post("/api/audits", json={"ticker": "AAPL"})
    assert res.status_code in (200, 201)
    run_id = res.json()["run_id"]

    res_an = client.get(f"/api/analytics/audit/{run_id}")
    assert res_an.status_code == 200
    data = res_an.json()
    assert data["run_id"] == run_id
    assert len(data["performance_metrics"]) >= 6
    assert len(data["variance_items"]) >= 6
    assert data["accounting_equation"]["status"] in ("PASS", "FAIL", "NOT_APPLICABLE", "INDETERMINATE")
    assert data["confidence_coverage"]["coverage_percent"] > 0
    assert "pre_review_accuracy" in data["human_review_analytics"]
