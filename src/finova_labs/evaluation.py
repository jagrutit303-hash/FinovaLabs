"""SEC Company Facts ground-truth comparison and accuracy evaluation for FinovaLabs."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from finova_labs.audit import record_audit_event
from finova_labs.database import (
    fetch_accuracy_evaluations,
    fetch_audit_run,
    fetch_extracted_metrics,
    get_connection,
    init_db,
    save_accuracy_evaluations,
)
from finova_labs.logging_config import get_logger
from finova_labs.metric_mapping import get_metric_definition
from finova_labs.normalization import classify_period, normalize_unit, parse_numeric_text
from finova_labs.sec_client import (
    COMPANY_FACTS_URL_TEMPLATE,
    SecEdgarClient,
    normalize_cik,
)
from finova_labs.settings import get_settings

logger = get_logger("evaluation")


class ReferenceMatchResult(BaseModel):
    """Result of resolving a matching SEC Company Facts ground-truth entry."""

    found: bool
    status: str  # MATCH_FOUND | UNAVAILABLE_REFERENCE | PERIOD_MISMATCH | UNIT_MISMATCH
    ground_truth_value: Decimal | None = None
    ground_truth_unit: str | None = None
    ground_truth_concept: str | None = None
    ground_truth_fiscal_period: str | None = None
    ground_truth_period_start: str | None = None
    ground_truth_period_end: str | None = None
    ground_truth_accession: str | None = None
    reference_source_url: str | None = None
    reference_fact_json: str | None = None
    explanation: str


class MetricComparisonRecord(BaseModel):
    """Pre- and post-human-review evaluation result for one extracted metric."""

    run_id: str
    metric_id: int | None = None
    cik: str
    ticker: str | None = None
    company_name: str | None = None
    accession_number: str
    form_type: str = "10-K"
    metric_name: str
    xbrl_concept: str | None = None
    unit: str
    fiscal_period: str | None = None
    fiscal_year: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    review_status: str = "NOT_REQUIRED"

    pre_review_value: Decimal | None = None
    post_review_value: Decimal | None = None
    ground_truth_value: Decimal | None = None
    ground_truth_unit: str | None = None
    ground_truth_concept: str | None = None
    ground_truth_fiscal_period: str | None = None
    ground_truth_period_start: str | None = None
    ground_truth_period_end: str | None = None
    ground_truth_accession: str | None = None

    pre_abs_diff: Decimal | None = None
    pre_pct_diff: Decimal | None = None
    pre_rel_diff: float | None = None
    pre_exact_match: bool = False
    pre_status: str

    post_abs_diff: Decimal | None = None
    post_pct_diff: Decimal | None = None
    post_rel_diff: float | None = None
    post_exact_match: bool = False
    post_status: str

    comparison_status: str
    explanation: str
    reference_source_url: str | None = None
    reference_fact_json: str | None = None
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_row(self) -> dict[str, Any]:
        """Serialize evaluation record into a SQLite-ready dictionary."""
        return {
            "run_id": self.run_id,
            "metric_id": self.metric_id,
            "cik": self.cik,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "accession_number": self.accession_number,
            "form_type": self.form_type,
            "metric_name": self.metric_name,
            "xbrl_concept": self.xbrl_concept,
            "unit": self.unit,
            "fiscal_period": self.fiscal_period,
            "fiscal_year": self.fiscal_year,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "extracted_value": float(self.pre_review_value)
            if self.pre_review_value is not None
            else None,
            "pre_review_decimal": str(self.pre_review_value)
            if self.pre_review_value is not None
            else None,
            "post_review_decimal": str(self.post_review_value)
            if self.post_review_value is not None
            else None,
            "review_status": self.review_status,
            "ground_truth_value": float(self.ground_truth_value)
            if self.ground_truth_value is not None
            else None,
            "ground_truth_decimal": str(self.ground_truth_value)
            if self.ground_truth_value is not None
            else None,
            "ground_truth_unit": self.ground_truth_unit,
            "ground_truth_concept": self.ground_truth_concept,
            "ground_truth_fiscal_period": self.ground_truth_fiscal_period,
            "ground_truth_period_start": self.ground_truth_period_start,
            "ground_truth_period_end": self.ground_truth_period_end,
            "ground_truth_accession": self.ground_truth_accession,
            "abs_diff": float(self.pre_abs_diff)
            if self.pre_abs_diff is not None
            else None,
            "rel_diff": self.pre_rel_diff,
            "matched": int(self.pre_exact_match),
            "pre_abs_diff": str(self.pre_abs_diff)
            if self.pre_abs_diff is not None
            else None,
            "pre_pct_diff": str(self.pre_pct_diff)
            if self.pre_pct_diff is not None
            else None,
            "pre_exact_match": int(self.pre_exact_match),
            "pre_status": self.pre_status,
            "post_abs_diff": str(self.post_abs_diff)
            if self.post_abs_diff is not None
            else None,
            "post_pct_diff": str(self.post_pct_diff)
            if self.post_pct_diff is not None
            else None,
            "post_exact_match": int(self.post_exact_match),
            "post_status": self.post_status,
            "comparison_status": self.comparison_status,
            "explanation": self.explanation,
            "reference_source_url": self.reference_source_url,
            "reference_fact_json": self.reference_fact_json,
            "evaluated_at": self.evaluated_at,
        }


class GroupAccuracyBreakdown(BaseModel):
    """Accuracy and coverage slice for a single company or metric."""

    group_key: str
    group_label: str
    cik: str | None = None
    ticker: str | None = None
    total_records: int
    extracted_present_count: int
    evaluable_count: int
    unavailable_reference_count: int
    unmatched_record_count: int
    period_mismatch_count: int
    unit_mismatch_count: int
    pre_exact_matches: int
    pre_mismatches: int
    post_exact_matches: int
    post_mismatches: int
    human_corrected_matches: int
    extraction_coverage: float
    ground_truth_coverage: float
    pre_review_accuracy_evaluable: float | None
    pre_review_accuracy_overall: float
    post_review_accuracy_evaluable: float | None
    post_review_accuracy_overall: float
    pre_denominator_label: str
    post_denominator_label: str
    coverage_denominator_label: str


class AccuracySummary(BaseModel):
    """Aggregate SEC Company Facts accuracy summary with transparent denominators."""

    total_records: int
    extracted_present_count: int
    evaluable_count: int
    unavailable_reference_count: int
    unmatched_record_count: int
    period_mismatch_count: int
    unit_mismatch_count: int
    pending_review_count: int
    pre_exact_matches: int
    pre_mismatches: int
    post_exact_matches: int
    post_mismatches: int
    human_corrected_matches: int
    extraction_coverage: float
    ground_truth_coverage: float
    pre_review_accuracy_evaluable: float | None
    pre_review_accuracy_overall: float
    post_review_accuracy_evaluable: float | None
    post_review_accuracy_overall: float
    pre_denominator_label: str
    post_denominator_label: str
    coverage_denominator_label: str
    status_counts: dict[str, int] = Field(default_factory=dict)
    by_company: list[GroupAccuracyBreakdown] = Field(default_factory=list)
    by_metric: list[GroupAccuracyBreakdown] = Field(default_factory=list)


def _strip_concept_namespace(concept: str | None) -> str | None:
    if not concept:
        return None
    cleaned = concept.strip()
    if ":" in cleaned:
        return cleaned.split(":", 1)[1].strip()
    return cleaned


def _row_decimal(row: dict[str, Any], dec_key: str, float_key: str | None = None) -> Decimal | None:
    raw = row.get(dec_key)
    if raw is not None and str(raw).strip():
        return parse_numeric_text(str(raw))
    if float_key and row.get(float_key) is not None:
        return parse_numeric_text(row[float_key])
    return None


def _dates_compatible(
    *,
    metric_name: str,
    rec_fp: str | None,
    rec_start: str | None,
    rec_end: str | None,
    item: dict[str, Any],
) -> tuple[bool, str | None]:
    """Verify period kind, fiscal period, start date, and end date alignment cleanly."""
    metric_def = get_metric_definition(metric_name)
    expected_kind = metric_def.period_type if metric_def is not None else "unknown"

    item_start = item.get("start")
    item_end = item.get("end")
    classification = classify_period(
        start_date=item_start,
        end_date=item_end,
        fp=item.get("fp"),
        frame=item.get("frame"),
        expected_kind=expected_kind,
    )

    rec_fp_clean = (rec_fp or "").strip().upper()
    item_fp_clean = (classification.fiscal_period or str(item.get("fp") or "")).strip().upper()
    if rec_fp_clean and item_fp_clean and rec_fp_clean != item_fp_clean:
        return False, f"fiscal_period '{item_fp_clean}' != '{rec_fp_clean}'"

    if rec_fp_clean == "FY" and not classification.is_annual:
        return False, f"period kind '{classification.period_kind}' is not annual FY"

    if rec_end and item_end and str(item_end).strip() != str(rec_end).strip():
        return False, f"period_end '{item_end}' != '{rec_end}'"

    if expected_kind != "instant" and rec_start and item_start:
        if str(item_start).strip() != str(rec_start).strip():
            return False, f"period_start '{item_start}' != '{rec_start}'"

    if expected_kind == "duration" and item_start is None and rec_start:
        return False, "instant Company Facts item cannot match duration metric"

    return True, None


def resolve_company_facts_reference(
    metric_row: dict[str, Any],
    company_facts_payload: dict[str, Any] | None,
) -> ReferenceMatchResult:
    """Resolve matching SEC Company Facts ground truth with strict company/concept/period/unit checks."""
    rec_cik = normalize_cik(str(metric_row.get("cik") or ""))
    accn = str(metric_row.get("accession_number") or "").strip()
    form_type = str(metric_row.get("form_type") or "10-K").strip().upper()
    metric_name = str(metric_row["metric_name"])
    rec_unit_raw = str(metric_row.get("unit") or "USD")
    rec_unit, _ = normalize_unit(rec_unit_raw, fallback_unit="USD")
    rec_fp = str(metric_row.get("fiscal_period") or "FY")
    rec_start = metric_row.get("period_start")
    rec_end = metric_row.get("period_end")
    base_url = COMPANY_FACTS_URL_TEMPLATE.format(cik=rec_cik)

    if not isinstance(company_facts_payload, dict):
        return ReferenceMatchResult(
            found=False,
            status="UNAVAILABLE_REFERENCE",
            reference_source_url=base_url,
            explanation="SEC Company Facts payload unavailable for comparison.",
        )

    # Support either full SEC Company Facts wrapper {"cik": ..., "facts": {"us-gaap": ...}} or raw {"us-gaap": ...}
    if "facts" in company_facts_payload and isinstance(company_facts_payload["facts"], dict):
        payload_cik = company_facts_payload.get("cik")
        if payload_cik is not None:
            try:
                norm_payload_cik = normalize_cik(payload_cik)
            except Exception:
                norm_payload_cik = str(payload_cik).strip()
            if norm_payload_cik != rec_cik:
                return ReferenceMatchResult(
                    found=False,
                    status="UNAVAILABLE_REFERENCE",
                    reference_source_url=base_url,
                    explanation=(
                        f"Company Facts CIK mismatch ({norm_payload_cik} != {rec_cik}); "
                        "refused cross-company comparison."
                    ),
                )
        facts_root = company_facts_payload["facts"]
    else:
        facts_root = company_facts_payload

    us_gaap = facts_root.get("us-gaap", {}) if isinstance(facts_root, dict) else {}
    if not isinstance(us_gaap, dict) or not us_gaap:
        return ReferenceMatchResult(
            found=False,
            status="UNAVAILABLE_REFERENCE",
            reference_source_url=base_url,
            explanation="SEC Company Facts 'us-gaap' taxonomy section is empty or unavailable.",
        )

    raw_concept = _strip_concept_namespace(metric_row.get("xbrl_concept"))
    if raw_concept:
        concept_candidates = [raw_concept]
    else:
        metric_def = get_metric_definition(metric_name)
        concept_candidates = list(metric_def.xbrl_concepts) if metric_def else []

    if not concept_candidates:
        return ReferenceMatchResult(
            found=False,
            status="UNAVAILABLE_REFERENCE",
            reference_source_url=base_url,
            explanation=f"No XBRL concept specified for metric '{metric_name}'.",
        )

    exact_matches: list[tuple[str, str, str, dict[str, Any], Decimal]] = []
    period_mismatch_notes: list[str] = []
    unit_mismatch_notes: list[str] = []

    for concept in concept_candidates:
        concept_obj = us_gaap.get(concept)
        if not isinstance(concept_obj, dict):
            continue
        units_map = concept_obj.get("units")
        if not isinstance(units_map, dict):
            continue

        for raw_unit_key, items in units_map.items():
            if not isinstance(items, list):
                continue
            gt_unit, _ = normalize_unit(raw_unit_key, fallback_unit=rec_unit)

            for item in items:
                if not isinstance(item, dict):
                    continue
                if accn and str(item.get("accn") or "").strip() != accn:
                    continue
                item_form = str(item.get("form") or "").strip().upper()
                if form_type and item_form and item_form != form_type:
                    continue

                if gt_unit != rec_unit:
                    unit_mismatch_notes.append(
                        f"us-gaap:{concept} unit '{raw_unit_key}' ({gt_unit}) != '{rec_unit}'"
                    )
                    continue

                period_ok, period_reason = _dates_compatible(
                    metric_name=metric_name,
                    rec_fp=rec_fp,
                    rec_start=rec_start,
                    rec_end=rec_end,
                    item=item,
                )
                if not period_ok:
                    if period_reason:
                        period_mismatch_notes.append(f"us-gaap:{concept}: {period_reason}")
                    continue

                gt_val = parse_numeric_text(item.get("val"))
                if gt_val is None:
                    continue
                exact_matches.append((concept, raw_unit_key, gt_unit, item, gt_val))

    if exact_matches:
        unique_values = {m[4] for m in exact_matches}
        chosen_concept, chosen_raw_unit, chosen_unit, chosen_item, chosen_val = exact_matches[0]
        if len(unique_values) > 1:
            return ReferenceMatchResult(
                found=False,
                status="UNAVAILABLE_REFERENCE",
                ground_truth_unit=chosen_unit,
                ground_truth_concept=f"us-gaap:{chosen_concept}",
                ground_truth_accession=chosen_item.get("accn"),
                reference_source_url=f"{base_url}#us-gaap:{chosen_concept}|accn={accn}",
                reference_fact_json=json.dumps([m[3] for m in exact_matches], ensure_ascii=False),
                explanation=(
                    f"Ambiguous SEC Company Facts ground truth: found {len(unique_values)} conflicting values "
                    f"for us-gaap:{chosen_concept} (accn={accn}, period={rec_fp} {rec_end})."
                ),
            )

        item_end = chosen_item.get("end")
        item_start = chosen_item.get("start")
        item_fp = str(chosen_item.get("fp") or rec_fp)
        source_frag = f"us-gaap:{chosen_concept}|accn={accn}|unit={chosen_raw_unit}|end={item_end}"
        return ReferenceMatchResult(
            found=True,
            status="MATCH_FOUND",
            ground_truth_value=chosen_val,
            ground_truth_unit=chosen_unit,
            ground_truth_concept=f"us-gaap:{chosen_concept}",
            ground_truth_fiscal_period=item_fp,
            ground_truth_period_start=item_start,
            ground_truth_period_end=item_end,
            ground_truth_accession=chosen_item.get("accn") or accn,
            reference_source_url=f"{base_url}#{source_frag}",
            reference_fact_json=json.dumps(
                {
                    "cik": rec_cik,
                    "concept": f"us-gaap:{chosen_concept}",
                    "raw_unit": chosen_raw_unit,
                    "normalized_unit": chosen_unit,
                    "entry": chosen_item,
                },
                ensure_ascii=False,
            ),
            explanation=(
                f"Matched SEC Company Facts us-gaap:{chosen_concept} ({chosen_unit}, "
                f"accn={accn}, {item_start or 'instant'}..{item_end})."
            ),
        )

    if period_mismatch_notes and unit_mismatch_notes:
        return ReferenceMatchResult(
            found=False,
            status="PERIOD_MISMATCH",
            reference_source_url=base_url,
            reference_fact_json=json.dumps(
                {"period_mismatches": period_mismatch_notes[:5], "unit_mismatches": unit_mismatch_notes[:5]},
                ensure_ascii=False,
            ),
            explanation=(
                "Refused comparison against SEC Company Facts: only non-matching periods/units found "
                f"({'; '.join((period_mismatch_notes + unit_mismatch_notes)[:3])})."
            ),
        )

    if period_mismatch_notes:
        return ReferenceMatchResult(
            found=False,
            status="PERIOD_MISMATCH",
            reference_source_url=base_url,
            reference_fact_json=json.dumps({"period_mismatches": period_mismatch_notes[:5]}, ensure_ascii=False),
            explanation=(
                "Refused cross-period comparison: SEC Company Facts entry for matching period unavailable "
                f"({'; '.join(period_mismatch_notes[:3])})."
            ),
        )

    if unit_mismatch_notes:
        return ReferenceMatchResult(
            found=False,
            status="UNIT_MISMATCH",
            reference_source_url=base_url,
            reference_fact_json=json.dumps({"unit_mismatches": unit_mismatch_notes[:5]}, ensure_ascii=False),
            explanation=(
                "Refused cross-unit comparison: SEC Company Facts entry has incompatible unit "
                f"({'; '.join(unit_mismatch_notes[:3])})."
            ),
        )

    return ReferenceMatchResult(
        found=False,
        status="UNAVAILABLE_REFERENCE",
        reference_source_url=base_url,
        explanation=(
            f"No SEC Company Facts entry found for concept(s) {', '.join(concept_candidates)} "
            f"in accn={accn} ({rec_fp}, {rec_unit})."
        ),
    )


def _compare_decimal_against_ground_truth(
    candidate: Decimal | None,
    ground_truth: Decimal | None,
    *,
    ref_status: str,
    rejected: bool = False,
) -> tuple[Decimal | None, Decimal | None, float | None, bool, str, str]:
    """Compare a single candidate Decimal against ground truth without mutating meaning."""
    if ref_status in {"PERIOD_MISMATCH", "UNIT_MISMATCH", "UNAVAILABLE_REFERENCE"} or ground_truth is None:
        if candidate is None:
            return (
                None,
                None,
                None,
                False,
                "UNAVAILABLE_REFERENCE" if ref_status == "UNAVAILABLE_REFERENCE" else ref_status,
                "Both extracted value and verifiable SEC Company Facts ground truth are unavailable.",
            )
        return (
            None,
            None,
            None,
            False,
            ref_status,
            "Verifiable SEC Company Facts ground truth unavailable; not counted as a match.",
        )

    if rejected:
        return (
            None,
            None,
            None,
            False,
            "UNMATCHED_RECORD",
            "Rejected during human review; excluded from post-review exact matches.",
        )

    if candidate is None:
        return (
            None,
            None,
            None,
            False,
            "UNMATCHED_RECORD",
            "Extracted metric is missing/unmatched while SEC Company Facts ground truth exists.",
        )

    abs_diff = abs(candidate - ground_truth)
    exact_match = abs_diff == Decimal(0)
    if ground_truth == Decimal(0):
        pct_diff: Decimal | None = None
        rel_diff: float | None = None
        pct_note = "percentage difference N/A (ground truth is 0)"
    else:
        rel_ratio = abs_diff / abs(ground_truth)
        pct_diff = (rel_ratio * Decimal("100")).quantize(Decimal("0.0001"))
        rel_diff = float(rel_ratio)
        pct_note = f"{pct_diff}%"

    if exact_match:
        return abs_diff, Decimal("0") if ground_truth != Decimal(0) else None, 0.0 if ground_truth != Decimal(0) else None, True, "EXACT_MATCH", "Exact match with SEC Company Facts ground truth."
    return (
        abs_diff,
        pct_diff,
        rel_diff,
        False,
        "MISMATCH",
        f"Abs diff={abs_diff}, pct diff={pct_note}.",
    )


def evaluate_metric_record(
    metric_row: dict[str, Any],
    company_facts_payload: dict[str, Any] | None,
    *,
    company_name: str | None = None,
) -> MetricComparisonRecord:
    """Evaluate one SQLite extracted_metrics row against SEC Company Facts (pre & post human review)."""
    run_id = str(metric_row["run_id"])
    cik = normalize_cik(str(metric_row["cik"]))
    accn = str(metric_row["accession_number"])
    metric_name = str(metric_row["metric_name"])
    review_status = str(metric_row.get("review_status") or "NOT_REQUIRED").upper()

    pre_val = _row_decimal(metric_row, "normalized_decimal", "normalized_value")
    if review_status == "REJECTED":
        post_val: Decimal | None = None
    elif review_status in {"APPROVED", "CORRECTED", "EDITED"}:
        reviewed_dec = _row_decimal(metric_row, "reviewed_decimal", "reviewed_value")
        post_val = reviewed_dec if reviewed_dec is not None else pre_val
    else:
        post_val = pre_val

    ref = resolve_company_facts_reference(metric_row, company_facts_payload)
    gt_val = ref.ground_truth_value if ref.found else None

    pre_abs, pre_pct, pre_rel, pre_exact, pre_status, pre_note = _compare_decimal_against_ground_truth(
        pre_val,
        gt_val,
        ref_status=ref.status,
        rejected=False,
    )
    post_abs, post_pct, post_rel, post_exact, post_status, post_note = _compare_decimal_against_ground_truth(
        post_val,
        gt_val,
        ref_status=ref.status,
        rejected=(review_status == "REJECTED"),
    )

    if pre_status == "EXACT_MATCH":
        comparison_status = "EXACT_MATCH"
    elif pre_status in {"PERIOD_MISMATCH", "UNIT_MISMATCH", "UNAVAILABLE_REFERENCE", "UNMATCHED_RECORD"}:
        comparison_status = pre_status
    else:
        comparison_status = "MISMATCH"

    explanation = f"{ref.explanation} Pre-review: {pre_note} Post-review ({review_status}): {post_note}"

    return MetricComparisonRecord(
        run_id=run_id,
        metric_id=metric_row.get("id"),
        cik=cik,
        ticker=metric_row.get("ticker"),
        company_name=company_name or metric_row.get("company_name"),
        accession_number=accn,
        form_type=str(metric_row.get("form_type") or "10-K"),
        metric_name=metric_name,
        xbrl_concept=metric_row.get("xbrl_concept"),
        unit=str(metric_row.get("unit") or "USD"),
        fiscal_period=metric_row.get("fiscal_period"),
        fiscal_year=metric_row.get("fiscal_year"),
        period_start=metric_row.get("period_start"),
        period_end=metric_row.get("period_end"),
        review_status=review_status,
        pre_review_value=pre_val,
        post_review_value=post_val,
        ground_truth_value=gt_val,
        ground_truth_unit=ref.ground_truth_unit,
        ground_truth_concept=ref.ground_truth_concept,
        ground_truth_fiscal_period=ref.ground_truth_fiscal_period,
        ground_truth_period_start=ref.ground_truth_period_start,
        ground_truth_period_end=ref.ground_truth_period_end,
        ground_truth_accession=ref.ground_truth_accession,
        pre_abs_diff=pre_abs,
        pre_pct_diff=pre_pct,
        pre_rel_diff=pre_rel,
        pre_exact_match=pre_exact,
        pre_status=pre_status,
        post_abs_diff=post_abs,
        post_pct_diff=post_pct,
        post_rel_diff=post_rel,
        post_exact_match=post_exact,
        post_status=post_status,
        comparison_status=comparison_status,
        explanation=explanation,
        reference_source_url=ref.reference_source_url,
        reference_fact_json=ref.reference_fact_json,
    )


def _compute_group_breakdown(
    group_key: str,
    group_label: str,
    rows: list[dict[str, Any]],
    *,
    cik: str | None = None,
    ticker: str | None = None,
) -> GroupAccuracyBreakdown:
    total = len(rows)
    extracted_present = sum(
        1 for r in rows if (r.get("pre_review_decimal") is not None or r.get("extracted_value") is not None)
    )
    evaluable = sum(
        1 for r in rows if (r.get("ground_truth_decimal") is not None or r.get("ground_truth_value") is not None)
    )
    unavailable_ref = total - evaluable
    period_mismatches = sum(1 for r in rows if r.get("pre_status") == "PERIOD_MISMATCH")
    unit_mismatches = sum(1 for r in rows if r.get("pre_status") == "UNIT_MISMATCH")
    unmatched_records = sum(
        1 for r in rows
        if r.get("pre_status") == "UNMATCHED_RECORD" or r.get("post_status") == "UNMATCHED_RECORD"
    )

    pre_matches = sum(1 for r in rows if bool(r.get("pre_exact_match")))
    pre_mismatches = sum(1 for r in rows if r.get("pre_status") == "MISMATCH")
    post_matches = sum(1 for r in rows if bool(r.get("post_exact_match")))
    post_mismatches = sum(1 for r in rows if r.get("post_status") == "MISMATCH")
    human_fixed = sum(
        1 for r in rows
        if not bool(r.get("pre_exact_match")) and bool(r.get("post_exact_match"))
    )

    ext_cov = round(extracted_present / total, 4) if total else 0.0
    gt_cov = round(evaluable / total, 4) if total else 0.0
    pre_eval_acc = round(pre_matches / evaluable, 4) if evaluable else None
    pre_overall_acc = round(pre_matches / total, 4) if total else 0.0
    post_eval_acc = round(post_matches / evaluable, 4) if evaluable else None
    post_overall_acc = round(post_matches / total, 4) if total else 0.0

    return GroupAccuracyBreakdown(
        group_key=group_key,
        group_label=group_label,
        cik=cik,
        ticker=ticker,
        total_records=total,
        extracted_present_count=extracted_present,
        evaluable_count=evaluable,
        unavailable_reference_count=unavailable_ref,
        unmatched_record_count=unmatched_records,
        period_mismatch_count=period_mismatches,
        unit_mismatch_count=unit_mismatches,
        pre_exact_matches=pre_matches,
        pre_mismatches=pre_mismatches,
        post_exact_matches=post_matches,
        post_mismatches=post_mismatches,
        human_corrected_matches=human_fixed,
        extraction_coverage=ext_cov,
        ground_truth_coverage=gt_cov,
        pre_review_accuracy_evaluable=pre_eval_acc,
        pre_review_accuracy_overall=pre_overall_acc,
        post_review_accuracy_evaluable=post_eval_acc,
        post_review_accuracy_overall=post_overall_acc,
        pre_denominator_label=f"{pre_matches}/{evaluable} verifiable ({pre_matches}/{total} total)",
        post_denominator_label=f"{post_matches}/{evaluable} verifiable ({post_matches}/{total} total)",
        coverage_denominator_label=f"{evaluable}/{total} GT ref ({extracted_present}/{total} extracted)",
    )


def summarize_accuracy_evaluations(
    evaluations: Iterable[dict[str, Any] | MetricComparisonRecord],
) -> AccuracySummary:
    """Compute pre/post-review accuracy, coverage, and company/metric breakdowns with denominators."""
    rows: list[dict[str, Any]] = [
        item.to_db_row() if isinstance(item, MetricComparisonRecord) else dict(item)
        for item in evaluations
    ]
    overall = _compute_group_breakdown("ALL", "All Records", rows)
    pending_reviews = sum(
        1 for r in rows if str(r.get("review_status") or "").upper() == "REVIEW_REQUIRED"
    )

    status_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        status_counts[str(r.get("pre_status") or r.get("comparison_status") or "UNAVAILABLE_REFERENCE")] += 1

    company_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = str(r.get("cik") or r.get("ticker") or r.get("run_id") or "UNKNOWN")
        company_buckets[key].append(r)

    by_company: list[GroupAccuracyBreakdown] = []
    for cik_key in sorted(company_buckets.keys()):
        bucket = company_buckets[cik_key]
        sample = bucket[0]
        ticker = sample.get("ticker")
        cname = sample.get("company_name") or ticker or cik_key
        label = f"{ticker} — {cname}" if ticker and ticker != cname else str(cname)
        by_company.append(
            _compute_group_breakdown(
                cik_key,
                label,
                bucket,
                cik=sample.get("cik"),
                ticker=ticker,
            )
        )

    metric_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        metric_buckets[str(r.get("metric_name") or "Unknown")].append(r)

    by_metric = [
        _compute_group_breakdown(m_name, m_name, metric_buckets[m_name])
        for m_name in sorted(metric_buckets.keys())
    ]

    return AccuracySummary(
        total_records=overall.total_records,
        extracted_present_count=overall.extracted_present_count,
        evaluable_count=overall.evaluable_count,
        unavailable_reference_count=overall.unavailable_reference_count,
        unmatched_record_count=overall.unmatched_record_count,
        period_mismatch_count=overall.period_mismatch_count,
        unit_mismatch_count=overall.unit_mismatch_count,
        pending_review_count=pending_reviews,
        pre_exact_matches=overall.pre_exact_matches,
        pre_mismatches=overall.pre_mismatches,
        post_exact_matches=overall.post_exact_matches,
        post_mismatches=overall.post_mismatches,
        human_corrected_matches=overall.human_corrected_matches,
        extraction_coverage=overall.extraction_coverage,
        ground_truth_coverage=overall.ground_truth_coverage,
        pre_review_accuracy_evaluable=overall.pre_review_accuracy_evaluable,
        pre_review_accuracy_overall=overall.pre_review_accuracy_overall,
        post_review_accuracy_evaluable=overall.post_review_accuracy_evaluable,
        post_review_accuracy_overall=overall.post_review_accuracy_overall,
        pre_denominator_label=overall.pre_denominator_label,
        post_denominator_label=overall.post_denominator_label,
        coverage_denominator_label=overall.coverage_denominator_label,
        status_counts=dict(sorted(status_counts.items())),
        by_company=by_company,
        by_metric=by_metric,
    )


def _load_cached_company_facts(cik: str) -> dict[str, Any] | None:
    """Load locally cached SEC Company Facts JSON without making network requests."""
    settings = get_settings()
    cik10 = normalize_cik(cik)
    cache_file = settings.resolve_path(settings.sec.cache_dir) / "companyfacts" / f"CIK{cik10}.json"
    if not cache_file.is_file():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable cached Company Facts %s: %s", cache_file, exc)
        return None


def evaluate_run_against_company_facts(
    run_id: str,
    *,
    company_facts: dict[str, Any] | None = None,
    use_cached_only: bool = False,
    force_refresh: bool = False,
    persist: bool = True,
    db_path: Path | str | None = None,
) -> tuple[list[MetricComparisonRecord], AccuracySummary]:
    """Evaluate all extracted metrics for an audit run against SEC Company Facts."""
    init_db(db_path)
    run_row = fetch_audit_run(run_id, db_path=db_path)
    metric_rows = fetch_extracted_metrics(run_id=run_id, db_path=db_path, limit=500)
    if not metric_rows:
        return [], summarize_accuracy_evaluations([])

    cik = normalize_cik(str((run_row or {}).get("cik") or metric_rows[0]["cik"]))
    company_name = (run_row or {}).get("company_name")

    payload = company_facts
    if payload is None:
        if use_cached_only:
            payload = _load_cached_company_facts(cik)
        else:
            client = SecEdgarClient()
            res = client.get_company_facts(cik, force_refresh=force_refresh)
            payload = {
                "cik": res.cik,
                "entityName": res.entity_name,
                "facts": res.facts,
            }

    comparisons = [
        evaluate_metric_record(row, payload, company_name=company_name)
        for row in metric_rows
    ]
    summary = summarize_accuracy_evaluations(comparisons)

    if persist:
        db_rows = [c.to_db_row() for c in comparisons]
        ticker = (run_row or {}).get("ticker") or metric_rows[0].get("ticker")
        filing_id = (run_row or {}).get("filing_id")
        accession_number = (run_row or {}).get("accession_number") or metric_rows[0].get("accession_number")
        pre_pct = (
            f"{summary.pre_review_accuracy_evaluable:.1%}"
            if summary.pre_review_accuracy_evaluable is not None
            else "N/A"
        )
        post_pct = (
            f"{summary.post_review_accuracy_evaluable:.1%}"
            if summary.post_review_accuracy_evaluable is not None
            else "N/A"
        )
        with get_connection(db_path) as conn:
            save_accuracy_evaluations(db_rows, run_id=run_id, db_path=db_path, conn=conn)
            record_audit_event(
                event_type="ACCURACY_EVALUATED",
                actor="evaluation",
                run_id=run_id,
                cik=cik,
                ticker=ticker,
                company_name=company_name,
                filing_id=filing_id,
                accession_number=accession_number,
                decision="ACCURACY_EVALUATED",
                explanation=(
                    f"Evaluated {summary.total_records} metric(s) against SEC Company Facts "
                    f"({summary.evaluable_count} evaluable; pre={pre_pct}, post={post_pct})."
                ),
                payload={
                    "cik": cik,
                    "ticker": ticker,
                    "company_name": company_name,
                    "accession_number": accession_number,
                    "total_records": summary.total_records,
                    "evaluable_count": summary.evaluable_count,
                    "pre_exact_matches": summary.pre_exact_matches,
                    "post_exact_matches": summary.post_exact_matches,
                    "pre_review_accuracy_evaluable": summary.pre_review_accuracy_evaluable,
                    "post_review_accuracy_evaluable": summary.post_review_accuracy_evaluable,
                    "ground_truth_coverage": summary.ground_truth_coverage,
                },
                conn=conn,
            )

    return comparisons, summary
