"""CSV and JSON report generation for completed FinovaLabs runs."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from finova_labs import PRODUCT_NAME, PRODUCT_TAGLINE
from finova_labs.evaluation import summarize_accuracy_evaluations

REPORT_BRANDING: dict[str, str] = {
    "application": PRODUCT_NAME,
    "tagline": PRODUCT_TAGLINE,
}


def build_report_metadata(
    run_id: str | None = None,
    report_type: str = "audit_summary",
) -> dict[str, Any]:
    """Build standardized FinovaLabs metadata for CSV/JSON report exports."""
    return {
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "report_type": report_type,
        "run_id": run_id or "pending",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def format_csv_header_comments(
    run_id: str | None = None,
    report_type: str = "audit_summary",
) -> list[str]:
    """Return branded comment header lines for exported CSV reports."""
    meta = build_report_metadata(run_id=run_id, report_type=report_type)
    return [
        f"# {meta['product']} - {meta['tagline']}",
        f"# Report Type: {meta['report_type']} | Run ID: {meta['run_id']} | Generated: {meta['generated_at_utc']}",
    ]


def build_accuracy_report_json(
    evaluations: list[dict[str, Any]],
    *,
    run_id: str | None = None,
) -> str:
    """Serialize FinovaLabs Company Facts accuracy comparisons and breakdowns to branded JSON."""
    summary = summarize_accuracy_evaluations(evaluations)
    payload = {
        "metadata": build_report_metadata(run_id=run_id, report_type="company_facts_accuracy"),
        "summary": summary.model_dump(mode="json"),
        "evaluations": evaluations,
    }
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False)


def build_accuracy_report_csv(
    evaluations: list[dict[str, Any]],
    *,
    run_id: str | None = None,
) -> str:
    """Serialize FinovaLabs Company Facts accuracy evaluations to branded CSV."""
    buf = io.StringIO()
    for line in format_csv_header_comments(run_id=run_id, report_type="company_facts_accuracy"):
        buf.write(line + "\n")

    fieldnames = [
        "run_id",
        "cik",
        "ticker",
        "company_name",
        "accession_number",
        "metric_name",
        "xbrl_concept",
        "unit",
        "fiscal_period",
        "fiscal_year",
        "period_start",
        "period_end",
        "review_status",
        "pre_review_decimal",
        "post_review_decimal",
        "ground_truth_decimal",
        "ground_truth_unit",
        "ground_truth_concept",
        "pre_abs_diff",
        "pre_pct_diff",
        "pre_exact_match",
        "pre_status",
        "post_abs_diff",
        "post_pct_diff",
        "post_exact_match",
        "post_status",
        "comparison_status",
        "reference_source_url",
        "explanation",
        "evaluated_at",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in evaluations:
        writer.writerow(row)
    return buf.getvalue()
