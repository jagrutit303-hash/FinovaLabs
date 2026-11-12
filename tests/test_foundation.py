"""Tests for FinovaLabs centralized settings, SQLite init, logging, and reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from finova_labs.database import (
    CORE_TABLES,
    check_db_health,
    fetch_accuracy_evaluations,
    fetch_dashboard_summary,
    fetch_extracted_metrics,
    fetch_review_tasks,
    fetch_runs,
    init_db,
)
from finova_labs.exceptions import ConfigurationError
from finova_labs.reporting import build_report_metadata, format_csv_header_comments
from finova_labs.settings import load_typed_settings


def test_settings_load_defaults_and_validation(tmp_path: Path) -> None:
    """Valid YAML loads cleanly and invalid thresholds raise ConfigurationError."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "app:\n  name: FinovaLabs\n  tagline: AI-Powered Financial Filing Auditor\n",
        encoding="utf-8",
    )
    settings = load_typed_settings(cfg_file)
    assert settings.app.name == "FinovaLabs"
    assert settings.app.db_path == "data/finova_labs.db"

    bad_cfg = tmp_path / "bad.yaml"
    bad_cfg.write_text(
        "confidence:\n  auto_approve_threshold: 0.50\n  review_required_threshold: 0.80\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_typed_settings(bad_cfg)


def test_database_init_and_empty_state_queries(tmp_path: Path) -> None:
    """SQLite initializes all 5 core tables and returns clean zero/empty results."""
    db_file = tmp_path / "finova_labs.db"
    init_db(db_file)

    health = check_db_health(db_file)
    assert health["healthy"] is True
    assert health["missing_tables"] == []
    assert set(health["table_counts"].keys()) == set(CORE_TABLES)

    summary = fetch_dashboard_summary(db_file)
    assert all(count == 0 for count in summary.values())
    assert fetch_runs(db_file) == []
    assert fetch_extracted_metrics(db_path=db_file) == []
    assert fetch_review_tasks(db_path=db_file) == []
    assert fetch_accuracy_evaluations(db_path=db_file) == []


def test_report_branding_metadata() -> None:
    """Report metadata embeds official FinovaLabs product name and tagline."""
    meta = build_report_metadata(run_id="run-123", report_type="audit_summary")
    assert meta["product"] == "FinovaLabs"
    assert meta["tagline"] == "AI-Powered Financial Filing Auditor"
    headers = format_csv_header_comments(run_id="run-123")
    assert "FinovaLabs" in headers[0]
    assert "AI-Powered Financial Filing Auditor" in headers[0]

