"""Automated tests for SEC Company Facts ground-truth accuracy evaluation and reporting."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from finova_labs.database import (
    create_audit_run,
    fetch_accuracy_evaluations,
    fetch_extracted_metrics,
    fetch_review_tasks,
    init_db,
    record_human_review_decision,
    save_extracted_metrics,
    sync_review_tasks_for_filing,
)
from finova_labs.evaluation import (
    evaluate_metric_record,
    evaluate_run_against_company_facts,
    summarize_accuracy_evaluations,
)
from finova_labs.reporting import build_accuracy_report_csv, build_accuracy_report_json


def _company_facts_payload(
    *,
    cik: int | str = "0000320193",
    accn: str = "0000320193-24-000123",
    rev_val: int | float = 391035000000,
    net_val: int | float = 93736000000,
    eps_val: float = 6.08,
    zero_val: int = 0,
    q1_only_assets: int = 350000000000,
    shares_only_equity: int = 15204137000,
) -> dict:
    return {
        "cik": cik,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": rev_val,
                                "accn": accn,
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                            }
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "val": net_val,
                                "accn": accn,
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                            }
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {
                                "val": eps_val,
                                "accn": accn,
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                            }
                        ]
                    }
                },
                "Liabilities": {
                    "units": {
                        "USD": [
                            {
                                "val": zero_val,
                                "accn": accn,
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "end": "2024-09-28",
                            }
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                # Quarterly/different period ONLY — must never compare against FY end
                                "val": q1_only_assets,
                                "accn": accn,
                                "form": "10-K",
                                "fp": "Q1",
                                "fy": 2024,
                                "end": "2023-12-30",
                            }
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "shares": [
                            {
                                # Incompatible unit — must never compare against USD metric
                                "val": shares_only_equity,
                                "accn": accn,
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "end": "2024-09-28",
                            }
                        ]
                    }
                },
            }
        },
    }


def _metric_row(
    *,
    run_id: str = "run-eval-1",
    cik: str = "0000320193",
    ticker: str = "AAPL",
    accn: str = "0000320193-24-000123",
    metric_name: str,
    xbrl_concept: str | None,
    val: str | None,
    unit: str = "USD",
    fp: str = "FY",
    start: str | None = "2023-10-01",
    end: str | None = "2024-09-28",
    review_status: str = "AUTO_APPROVED",
    reviewed_decimal: str | None = None,
) -> dict:
    return {
        "id": 1,
        "run_id": run_id,
        "cik": cik,
        "ticker": ticker,
        "company_name": "Apple Inc.",
        "accession_number": accn,
        "form_type": "10-K",
        "metric_name": metric_name,
        "xbrl_concept": xbrl_concept,
        "normalized_decimal": val,
        "normalized_value": float(val) if val is not None else None,
        "unit": unit,
        "fiscal_period": fp,
        "fiscal_year": 2024,
        "period_start": start,
        "period_end": end,
        "review_status": review_status,
        "reviewed_decimal": reviewed_decimal,
        "reviewed_value": float(reviewed_decimal) if reviewed_decimal is not None else None,
    }


def test_exact_match_mismatch_zero_gt_period_and_unit_guards() -> None:
    """Verify exact match, abs/pct diff, zero-GT safety, period guard, unit guard, and missing GT."""
    payload = _company_facts_payload()

    # 1. Exact match (Revenue)
    exact = evaluate_metric_record(
        _metric_row(metric_name="Revenue", xbrl_concept="Revenues", val="391035000000"),
        payload,
    )
    assert exact.pre_exact_match is True
    assert exact.pre_status == "EXACT_MATCH"
    assert exact.pre_abs_diff == Decimal("0")
    assert exact.pre_pct_diff == Decimal("0")
    assert exact.ground_truth_value == Decimal("391035000000")
    assert exact.reference_source_url is not None and "CIK0000320193.json" in exact.reference_source_url
    assert exact.reference_fact_json is not None and "391035000000" in exact.reference_fact_json

    # 2. Numeric mismatch with meaningful percentage diff (Net Income off by 10%)
    mismatch = evaluate_metric_record(
        _metric_row(metric_name="Net Income", xbrl_concept="NetIncomeLoss", val="103109600000"),
        payload,
    )
    assert mismatch.pre_exact_match is False
    assert mismatch.pre_status == "MISMATCH"
    assert mismatch.pre_abs_diff == Decimal("9373600000")
    assert mismatch.pre_pct_diff == Decimal("10.0000")

    # 3. Ground truth == 0 -> abs diff reported cleanly, pct diff is None (not division by zero)
    zero_gt = evaluate_metric_record(
        _metric_row(
            metric_name="Total Liabilities",
            xbrl_concept="Liabilities",
            val="1000",
            start=None,
        ),
        payload,
    )
    assert zero_gt.pre_status == "MISMATCH"
    assert zero_gt.pre_abs_diff == Decimal("1000")
    assert zero_gt.pre_pct_diff is None

    # 4. Mismatched fiscal period (Q1 in SEC vs FY extracted) -> NEVER compares or matches
    period_guard = evaluate_metric_record(
        _metric_row(metric_name="Total Assets", xbrl_concept="Assets", val="350000000000", start=None),
        payload,
    )
    assert period_guard.pre_exact_match is False
    assert period_guard.pre_status == "PERIOD_MISMATCH"
    assert period_guard.ground_truth_value is None

    # 5. Incompatible unit ('shares' in SEC vs 'USD' extracted) -> NEVER compares or matches
    unit_guard = evaluate_metric_record(
        _metric_row(
            metric_name="Shareholders' Equity",
            xbrl_concept="StockholdersEquity",
            val="15204137000",
            unit="USD",
            start=None,
        ),
        payload,
    )
    assert unit_guard.pre_exact_match is False
    assert unit_guard.pre_status == "UNIT_MISMATCH"
    assert unit_guard.ground_truth_value is None

    # 6. Missing SEC concept (unavailable GT) -> NEVER counted as match
    unavailable_gt = evaluate_metric_record(
        _metric_row(metric_name="Operating Cash Flow", xbrl_concept="MissingConceptXYZ", val="118254000000"),
        payload,
    )
    assert unavailable_gt.pre_exact_match is False
    assert unavailable_gt.pre_status == "UNAVAILABLE_REFERENCE"
    assert unavailable_gt.ground_truth_value is None

    # 7. Unmatched extracted record while SEC Company Facts HAS ground truth
    unmatched = evaluate_metric_record(
        _metric_row(
            metric_name="Earnings Per Share",
            xbrl_concept="EarningsPerShareDiluted",
            val=None,
            unit="USD/shares",
        ),
        payload,
    )
    assert unmatched.pre_exact_match is False
    assert unmatched.pre_status == "UNMATCHED_RECORD"
    assert unmatched.ground_truth_value == Decimal("6.08")

    # 8. Cross-company CIK mismatch -> refused!
    cross_company = evaluate_metric_record(
        _metric_row(metric_name="Revenue", xbrl_concept="Revenues", val="391035000000"),
        _company_facts_payload(cik="0000789019"),
    )
    assert cross_company.pre_exact_match is False
    assert cross_company.pre_status == "UNAVAILABLE_REFERENCE"
    assert "CIK mismatch" in cross_company.explanation


def test_pre_vs_post_review_separation_and_sqlite_breakdowns(tmp_path: Path) -> None:
    """Human corrections improve post-review accuracy without hiding raw pre-review errors."""
    db_path = tmp_path / "eval_workflow.db"
    init_db(db_path)

    aapl_accn = "0000320193-24-000123"
    msft_accn = "0000789019-24-000456"

    create_audit_run(
        run_id="run-aapl",
        cik="0000320193",
        accession_number=aapl_accn,
        company_name="Apple Inc.",
        ticker="AAPL",
        form_type="10-K",
        fiscal_year=2024,
        status="COMPLETED",
        current_stage="FINALIZED",
        db_path=db_path,
    )
    create_audit_run(
        run_id="run-msft",
        cik="0000789019",
        accession_number=msft_accn,
        company_name="Microsoft Corp",
        ticker="MSFT",
        form_type="10-K",
        fiscal_year=2024,
        status="COMPLETED",
        current_stage="FINALIZED",
        db_path=db_path,
    )

    # AAPL metrics:
    # - Revenue: exact match & AUTO_APPROVED
    # - Net Income: raw extraction wrong (80B instead of 93.736B), escalated and CORRECTED by human to 93.736B!
    # - Operating Cash Flow: MISSING extraction (UNMATCHED_RECORD) while no GT either -> UNAVAILABLE_REFERENCE
    save_extracted_metrics(
        [
            {
                "run_id": "run-aapl",
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": aapl_accn,
                "form_type": "10-K",
                "metric_name": "Revenue",
                "xbrl_concept": "Revenues",
                "raw_value": "391035000000",
                "normalized_value": 391035000000.0,
                "normalized_decimal": "391035000000",
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": "2023-10-01",
                "period_end": "2024-09-28",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "source_evidence": "us-gaap:Revenues",
                "evidence_location": "HTML Table 1",
                "extraction_status": "EXTRACTED",
                "validation_status": "PASS",
                "review_status": "AUTO_APPROVED",
                "created_at": "2026-11-12T00:00:00+00:00",
            },
            {
                "run_id": "run-aapl",
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": aapl_accn,
                "form_type": "10-K",
                "metric_name": "Net Income",
                "xbrl_concept": "NetIncomeLoss",
                "raw_value": "80000000000",
                "normalized_value": 80000000000.0,
                "normalized_decimal": "80000000000",
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": "2023-10-01",
                "period_end": "2024-09-28",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "source_evidence": "us-gaap:NetIncomeLoss",
                "evidence_location": "CompanyFacts JSON",
                "extraction_status": "EXTRACTED",
                "validation_status": "PASS",
                "review_status": "REVIEW_REQUIRED",
                "created_at": "2026-11-12T00:00:00+00:00",
            },
            {
                "run_id": "run-aapl",
                "cik": "0000320193",
                "ticker": "AAPL",
                "accession_number": aapl_accn,
                "form_type": "10-K",
                "metric_name": "Operating Cash Flow",
                "xbrl_concept": None,
                "raw_value": None,
                "normalized_value": None,
                "normalized_decimal": None,
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": "2023-10-01",
                "period_end": "2024-09-28",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
                "source_evidence": "Missing",
                "evidence_location": "None",
                "extraction_status": "MISSING",
                "validation_status": "NOT_APPLICABLE",
                "review_status": "REVIEW_REQUIRED",
                "created_at": "2026-11-12T00:00:00+00:00",
            },
        ],
        cik="0000320193",
        accession_number=aapl_accn,
        db_path=db_path,
    )

    # Human analyst corrects Net Income to exact SEC value and rejects Operating Cash Flow
    aapl_rows = fetch_extracted_metrics(run_id="run-aapl", db_path=db_path)
    ni_id = next(r["id"] for r in aapl_rows if r["metric_name"] == "Net Income")
    ocf_id = next(r["id"] for r in aapl_rows if r["metric_name"] == "Operating Cash Flow")
    sync_review_tasks_for_filing(
        tasks=[
            {
                "run_id": "run-aapl",
                "ticker": "AAPL",
                "metric_id": ni_id,
                "metric_name": "Net Income",
                "reason": "Low confidence",
            },
            {
                "run_id": "run-aapl",
                "ticker": "AAPL",
                "metric_id": ocf_id,
                "metric_name": "Operating Cash Flow",
                "reason": "Missing value",
            },
        ],
        cik="0000320193",
        accession_number=aapl_accn,
        db_path=db_path,
    )
    from finova_labs.database import fetch_review_tasks

    tasks = fetch_review_tasks(run_id="run-aapl", db_path=db_path)
    ni_task = next(t for t in tasks if t["metric_name"] == "Net Income")
    ocf_task = next(t for t in tasks if t["metric_name"] == "Operating Cash Flow")
    record_human_review_decision(
        task_id=ni_task["task_id"],
        action="EDIT",
        corrected_value="93736000000",
        reviewer_note="Fixed Net Income from Consolidated Statements of Operations.",
        db_path=db_path,
    )
    record_human_review_decision(
        task_id=ocf_task["task_id"],
        action="REJECT",
        reviewer_note="Missing OCF requires manual restatement check.",
        db_path=db_path,
    )

    # MSFT Revenue exact match
    save_extracted_metrics(
        [
            {
                "run_id": "run-msft",
                "cik": "0000789019",
                "ticker": "MSFT",
                "accession_number": msft_accn,
                "form_type": "10-K",
                "metric_name": "Revenue",
                "xbrl_concept": "Revenues",
                "raw_value": "245122000000",
                "normalized_value": 245122000000.0,
                "normalized_decimal": "245122000000",
                "unit": "USD",
                "currency": "USD",
                "scale_factor": 1,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "period_start": "2023-07-01",
                "period_end": "2024-06-30",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json",
                "source_evidence": "us-gaap:Revenues",
                "evidence_location": "HTML Table 1",
                "extraction_status": "EXTRACTED",
                "validation_status": "PASS",
                "review_status": "AUTO_APPROVED",
                "created_at": "2026-11-12T00:00:00+00:00",
            }
        ],
        cik="0000789019",
        accession_number=msft_accn,
        db_path=db_path,
    )

    aapl_facts = _company_facts_payload(cik="0000320193", accn=aapl_accn)
    msft_facts = {
        "cik": 789019,
        "entityName": "Microsoft Corp",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 245122000000,
                                "accn": msft_accn,
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2024,
                                "start": "2023-07-01",
                                "end": "2024-06-30",
                            }
                        ]
                    }
                }
            }
        },
    }

    evaluate_run_against_company_facts("run-aapl", company_facts=aapl_facts, persist=True, db_path=db_path)
    # Re-evaluating the same run replaces without duplicating rows!
    evaluate_run_against_company_facts("run-aapl", company_facts=aapl_facts, persist=True, db_path=db_path)
    evaluate_run_against_company_facts("run-msft", company_facts=msft_facts, persist=True, db_path=db_path)

    stored = fetch_accuracy_evaluations(limit=100, db_path=db_path)
    assert len(stored) == 4  # 3 AAPL + 1 MSFT, zero duplicates

    summary = summarize_accuracy_evaluations(stored)
    # Denominators:
    # Total records = 4 (3 extracted present, 1 missing OCF)
    # Evaluable with GT = 3 (AAPL Revenue, AAPL Net Income, MSFT Revenue); OCF has unavailable GT -> excluded from verifiable denom!
    # Pre-review matches = 2/3 verifiable (2/4 overall)
    # Post-review matches = 3/3 verifiable (3/4 overall), human_corrected_matches = 1
    assert summary.total_records == 4
    assert summary.extracted_present_count == 3
    assert summary.evaluable_count == 3
    assert summary.unavailable_reference_count == 1
    assert summary.pre_exact_matches == 2
    assert summary.post_exact_matches == 3
    assert summary.human_corrected_matches == 1
    assert summary.pre_review_accuracy_evaluable == round(2 / 3, 4)
    assert summary.post_review_accuracy_evaluable == 1.0
    assert summary.pre_review_accuracy_overall == 0.5
    assert summary.post_review_accuracy_overall == 0.75
    assert "2/3 verifiable" in summary.pre_denominator_label
    assert "3/3 verifiable" in summary.post_denominator_label

    # Breakdowns by company & by metric
    company_map = {c.ticker: c for c in summary.by_company}
    assert company_map["AAPL"].pre_exact_matches == 1
    assert company_map["AAPL"].post_exact_matches == 2
    assert company_map["AAPL"].evaluable_count == 2
    assert company_map["MSFT"].pre_review_accuracy_evaluable == 1.0

    metric_map = {m.group_key: m for m in summary.by_metric}
    assert metric_map["Revenue"].pre_exact_matches == 2
    assert metric_map["Net Income"].pre_exact_matches == 0
    assert metric_map["Net Income"].post_exact_matches == 1

    # Branded CSV & JSON exports preserve reference provenance and pre/post figures
    csv_out = build_accuracy_report_csv(stored)
    assert "# FinovaLabs - AI-Powered Financial Filing Auditor" in csv_out
    assert "pre_review_decimal" in csv_out
    assert "reference_source_url" in csv_out

    json_payload = json.loads(build_accuracy_report_json(stored))
    assert json_payload["metadata"]["product"] == "FinovaLabs"
    assert json_payload["summary"]["pre_exact_matches"] == 2
    assert json_payload["summary"]["post_exact_matches"] == 3
    assert len(json_payload["summary"]["by_company"]) == 2

