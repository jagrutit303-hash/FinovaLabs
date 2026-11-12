"""Financial validation rules: accounting identity, segment reconciliation, and YoY checks."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from finova_labs.audit import record_audit_event
from finova_labs.database import (
    apply_validation_outcomes_to_filing,
    get_connection,
    init_db,
    save_validation_results,
)
from finova_labs.filing_parser import HtmlFactEvidence, ParsedFilingHtml, parse_filing_html
from finova_labs.logging_config import get_logger
from finova_labs.metric_mapping import MetricDefinition, get_metric_definition
from finova_labs.normalization import classify_period, normalize_unit, parse_numeric_text
from finova_labs.settings import ValidationSettings, get_settings

if TYPE_CHECKING:
    from finova_labs.extractor import ExtractedMetricRecord

logger = get_logger("validators")

ValidationStatus = Literal["PASS", "FAIL", "WARNING", "NOT_APPLICABLE"]

ACCOUNTING_EQUATION_TOLERANCE_DOC = (
    "Documented Accounting Equation Tolerance: "
    "abs(Total Assets - (Total Liabilities + Shareholders' Equity)) must be within "
    "max(2 * max_scale_factor USD, abs(Total Assets) * accounting_identity_tolerance), "
    "where 2 * max_scale_factor absorbs display-unit rounding (e.g. $1M or $1K tables) and "
    "accounting_identity_tolerance (default 0.0005 = 0.05%) caps relative rounding drift."
)

_SEGMENT_EXCLUSION_TOKENS = (
    "total",
    "consolidated",
    "consolidation",
    "elimination",
    "eliminations",
    "reconciling",
    "corporate",
    "unallocated",
    "intersegment",
)


class SegmentRevenueItem(BaseModel):
    """Single comparable operating/business segment revenue disclosure."""

    segment_name: str
    value: Decimal
    reported_unit: str = "USD"
    currency: str = "USD"
    period_start: str | None = None
    period_end: str | None = None
    concept: str | None = None
    source_location: str | None = None


class PriorPeriodPoint(BaseModel):
    """Comparable prior-year fact resolved from prior records or SEC Company Facts."""

    metric_name: str
    concept: str | None = None
    value: Decimal
    reported_unit: str = "USD"
    currency: str = "USD"
    period_start: str | None = None
    period_end: str
    fiscal_year: int | None = None
    accession_number: str | None = None
    filed_date: str | None = None
    form_type: str | None = None
    restated: bool = False
    original_value: Decimal | None = None
    restatement_note: str | None = None


class ValidationResult(BaseModel):
    """Auditable validation outcome with explanation, metric references, and timestamp."""

    validation_id: str = Field(default_factory=lambda: f"val-{uuid.uuid4().hex[:10]}")
    rule_name: str  # accounting_equation | segment_revenue | yoy_comparison
    metric_name: str
    status: ValidationStatus
    explanation: str
    input_metric_refs: list[dict[str, Any]] = Field(default_factory=list)
    affected_metrics: list[str] = Field(default_factory=list)
    expected_value: Decimal | None = None
    actual_value: Decimal | None = None
    variance_abs: Decimal | None = None
    variance_pct: Decimal | None = None
    tolerance_used: str | None = None
    escalate_to_review: bool = False
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_row(
        self,
        *,
        cik: str,
        ticker: str | None,
        accession_number: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Serialize validation result into a SQLite-ready dictionary."""
        return {
            "validation_id": self.validation_id,
            "run_id": run_id,
            "cik": cik,
            "ticker": ticker,
            "accession_number": accession_number,
            "rule_name": self.rule_name,
            "metric_name": self.metric_name,
            "status": self.status,
            "explanation": self.explanation,
            "input_metric_refs_json": json.dumps(self.input_metric_refs, default=str, ensure_ascii=False),
            "expected_value": str(self.expected_value) if self.expected_value is not None else None,
            "actual_value": str(self.actual_value) if self.actual_value is not None else None,
            "variance_abs": str(self.variance_abs) if self.variance_abs is not None else None,
            "variance_pct": str(self.variance_pct) if self.variance_pct is not None else None,
            "tolerance_used": self.tolerance_used,
            "escalated": self.escalate_to_review,
            "evaluated_at": self.evaluated_at,
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _metric_ref(rec: ExtractedMetricRecord, role: str) -> dict[str, Any]:
    """Create a traceable input metric reference dictionary."""
    return {
        "role": role,
        "metric_name": rec.metric_name,
        "xbrl_concept": rec.xbrl_concept,
        "normalized_value": str(rec.normalized_value) if rec.normalized_value is not None else None,
        "unit": rec.reported_unit,
        "currency": rec.currency,
        "scale_factor": str(rec.scale_factor),
        "period_start": rec.period_start,
        "period_end": rec.period_end,
        "fiscal_year": rec.fiscal_year,
        "accession_number": rec.accession_number,
        "extraction_status": rec.extraction_status,
    }


def _fmt_money(val: Decimal | None, unit: str = "USD") -> str:
    if val is None:
        return "N/A"
    if unit == "USD/shares":
        return f"${val:,.2f}/sh"
    if unit.upper() == "USD":
        return f"${val:,.0f}" if val == val.to_integral_value() else f"${val:,.2f}"
    return f"{val:,.2f} {unit}"


def validate_accounting_equation(
    records: list[ExtractedMetricRecord],
    settings: ValidationSettings | None = None,
) -> ValidationResult:
    """Validate Total Assets = Total Liabilities + Shareholders' Equity within rounding tolerance."""
    val_settings = settings or get_settings().validation
    by_name = {r.metric_name: r for r in records}

    required_names = ("Total Assets", "Total Liabilities", "Shareholders' Equity")
    assets = by_name.get("Total Assets")
    liabilities = by_name.get("Total Liabilities")
    equity = by_name.get("Shareholders' Equity")

    present = [r for r in (assets, liabilities, equity) if r is not None]
    refs = [_metric_ref(r, r.metric_name.lower().replace(" ", "_").replace("'", "")) for r in present]

    missing_or_invalid = [
        name
        for name in required_names
        if by_name.get(name) is None
        or by_name[name].extraction_status != "EXTRACTED"
        or by_name[name].normalized_value is None
    ]
    if missing_or_invalid:
        return ValidationResult(
            rule_name="accounting_equation",
            metric_name="Accounting Equation (A = L + E)",
            status="NOT_APPLICABLE",
            explanation=(
                "Accounting equation check is not applicable because required balance sheet "
                f"metric(s) are unavailable or unextracted: {', '.join(missing_or_invalid)}."
            ),
            input_metric_refs=refs,
            affected_metrics=[],
            tolerance_used=ACCOUNTING_EQUATION_TOLERANCE_DOC,
        )

    assert assets is not None and liabilities is not None and equity is not None
    assert (
        assets.normalized_value is not None
        and liabilities.normalized_value is not None
        and equity.normalized_value is not None
    )

    units = {assets.reported_unit, liabilities.reported_unit, equity.reported_unit}
    currencies = {assets.currency, liabilities.currency, equity.currency}
    if len(units) > 1 or len(currencies) > 1:
        return ValidationResult(
            rule_name="accounting_equation",
            metric_name="Accounting Equation (A = L + E)",
            status="NOT_APPLICABLE",
            explanation=(
                "Accounting equation inputs are non-comparable due to mismatched units/currencies: "
                f"units={sorted(units)}, currencies={sorted(currencies)}."
            ),
            input_metric_refs=refs,
            affected_metrics=[],
            tolerance_used=ACCOUNTING_EQUATION_TOLERANCE_DOC,
        )

    dates = [_parse_date(r.period_end) for r in (assets, liabilities, equity)]
    if all(d is not None for d in dates):
        min_d, max_d = min(dates), max(dates)  # type: ignore[type-var]
        if (max_d - min_d).days > 7:
            return ValidationResult(
                rule_name="accounting_equation",
                metric_name="Accounting Equation (A = L + E)",
                status="NOT_APPLICABLE",
                explanation=(
                    "Balance sheet inputs span inconsistent period-end dates "
                    f"({assets.period_end}, {liabilities.period_end}, {equity.period_end}); "
                    "equation check skipped as non-comparable."
                ),
                input_metric_refs=refs,
                affected_metrics=[],
                tolerance_used=ACCOUNTING_EQUATION_TOLERANCE_DOC,
            )

    a_val = assets.normalized_value
    l_val = liabilities.normalized_value
    e_val = equity.normalized_value
    rhs = l_val + e_val
    abs_diff = abs(a_val - rhs)
    rel_diff = (abs_diff / abs(a_val)) if a_val != Decimal(0) else Decimal(0)

    max_scale = max(assets.scale_factor, liabilities.scale_factor, equity.scale_factor, Decimal(1))
    scale_allowance = Decimal(2) * max_scale
    rel_allowance = abs(a_val) * Decimal(str(val_settings.accounting_identity_tolerance))
    effective_allowance = max(scale_allowance, rel_allowance)
    tol_desc = (
        f"max(2 * scale={_fmt_money(scale_allowance)}, "
        f"{val_settings.accounting_identity_tolerance:.2%} of Assets={_fmt_money(rel_allowance)}) "
        f"= {_fmt_money(effective_allowance)}"
    )

    if abs_diff <= effective_allowance:
        return ValidationResult(
            rule_name="accounting_equation",
            metric_name="Accounting Equation (A = L + E)",
            status="PASS",
            explanation=(
                f"Accounting identity holds within documented rounding tolerance: "
                f"Total Assets {_fmt_money(a_val)} vs Liabilities + Equity {_fmt_money(rhs)} "
                f"(variance {_fmt_money(abs_diff)}, {rel_diff:.4%}; allowed {tol_desc})."
            ),
            input_metric_refs=refs,
            affected_metrics=list(required_names),
            expected_value=rhs,
            actual_value=a_val,
            variance_abs=abs_diff,
            variance_pct=rel_diff,
            tolerance_used=tol_desc,
            escalate_to_review=False,
        )

    return ValidationResult(
        rule_name="accounting_equation",
        metric_name="Accounting Equation (A = L + E)",
        status="FAIL",
        explanation=(
            f"Accounting equation violation: Total Assets ({_fmt_money(a_val)}) does not equal "
            f"Total Liabilities ({_fmt_money(l_val)}) + Shareholders' Equity ({_fmt_money(e_val)}) "
            f"= {_fmt_money(rhs)}. Variance of {_fmt_money(abs_diff)} ({rel_diff:.4%}) exceeds "
            f"documented tolerance ({tol_desc})."
        ),
        input_metric_refs=refs,
        affected_metrics=list(required_names),
        expected_value=rhs,
        actual_value=a_val,
        variance_abs=abs_diff,
        variance_pct=rel_diff,
        tolerance_used=tol_desc,
        escalate_to_review=True,
    )


def extract_comparable_segment_revenues(
    parsed_html: ParsedFilingHtml | None,
    consolidated_revenue: ExtractedMetricRecord | None,
) -> tuple[list[SegmentRevenueItem], str | None]:
    """Extract comparable annual business segment revenue facts from Inline XBRL HTML."""
    if parsed_html is None:
        return [], "10-K HTML was not supplied or parsed for segment disclosure checks."

    if (
        consolidated_revenue is None
        or consolidated_revenue.extraction_status != "EXTRACTED"
        or consolidated_revenue.normalized_value is None
    ):
        return [], "Consolidated Revenue is unavailable or unextracted for segment comparison."

    rev_def = get_metric_definition("Revenue")
    rev_concepts = set(rev_def.xbrl_concepts if rev_def else ()) | {
        "SegmentReportingInformationRevenue",
    }

    target_end = consolidated_revenue.period_end
    target_start = consolidated_revenue.period_start
    target_unit = consolidated_revenue.reported_unit

    best_by_member: dict[str, HtmlFactEvidence] = {}
    saw_other_axes = False
    saw_eliminations = False

    for concept in rev_concepts:
        for fact in parsed_html.facts_by_concept.get(concept, []):
            if not fact.has_dimensions or not fact.dimensions:
                continue
            if fact.reported_unit != target_unit:
                continue
            if target_end and fact.period_end != target_end:
                continue
            if target_start and fact.period_start and fact.period_start != target_start:
                continue

            classification = classify_period(
                start_date=fact.period_start,
                end_date=fact.period_end,
                fp="FY",
                expected_kind="duration",
            )
            if not classification.is_annual:
                continue

            if "StatementBusinessSegmentsAxis" not in fact.dimensions:
                saw_other_axes = True
                continue

            if len(fact.dimensions) > 1:
                axis_names = {k.lower() for k in fact.dimensions}
                if any("consolidation" in a or "elimination" in a for a in axis_names):
                    saw_eliminations = True
                else:
                    saw_other_axes = True
                continue

            member = fact.dimensions["StatementBusinessSegmentsAxis"]
            member_lower = member.lower()
            if any(tok in member_lower for tok in _SEGMENT_EXCLUSION_TOKENS):
                if "elimination" in member_lower or "corporate" in member_lower or "unallocated" in member_lower:
                    saw_eliminations = True
                continue

            if member not in best_by_member:
                best_by_member[member] = fact

    if len(best_by_member) < 2:
        if saw_eliminations:
            return [], (
                "Dimensional revenue disclosures include unallocated corporate or consolidation "
                "elimination adjustments without a clean standalone reportable segment sum."
            )
        if saw_other_axes:
            return [], (
                "Disclosed revenue dimensions only cover non-segment axes (such as product/geography) "
                "rather than comparable reportable business segments on StatementBusinessSegmentsAxis."
            )
        return [], (
            "No comparable multi-segment annual revenue facts were tagged on "
            "StatementBusinessSegmentsAxis in the 10-K Inline XBRL document."
        )

    items = [
        SegmentRevenueItem(
            segment_name=member,
            value=fact.normalized_value,
            reported_unit=fact.reported_unit,
            currency=fact.currency,
            period_start=fact.period_start,
            period_end=fact.period_end,
            concept=fact.concept,
            source_location=fact.evidence_location,
        )
        for member, fact in best_by_member.items()
    ]
    return items, None


def validate_segment_revenue(
    consolidated_revenue: ExtractedMetricRecord | None,
    *,
    parsed_html: ParsedFilingHtml | None = None,
    segment_items: list[SegmentRevenueItem] | None = None,
    settings: ValidationSettings | None = None,
) -> ValidationResult:
    """Validate disclosed operating segment revenue sum against consolidated Revenue."""
    val_settings = settings or get_settings().validation
    refs: list[dict[str, Any]] = []
    if consolidated_revenue is not None:
        refs.append(_metric_ref(consolidated_revenue, "consolidated_revenue"))

    if (
        consolidated_revenue is None
        or consolidated_revenue.extraction_status != "EXTRACTED"
        or consolidated_revenue.normalized_value is None
        or consolidated_revenue.normalized_value <= Decimal(0)
    ):
        return ValidationResult(
            rule_name="segment_revenue",
            metric_name="Segment Revenue Reconciliation",
            status="NOT_APPLICABLE",
            explanation=(
                "Segment revenue reconciliation is not applicable because consolidated Revenue is "
                "missing, non-positive, or unextracted."
            ),
            input_metric_refs=refs,
            affected_metrics=[],
        )

    resolved_segments: list[SegmentRevenueItem]
    unavailable_reason: str | None = None
    if segment_items is not None:
        resolved_segments = list(segment_items)
    else:
        resolved_segments, unavailable_reason = extract_comparable_segment_revenues(
            parsed_html=parsed_html,
            consolidated_revenue=consolidated_revenue,
        )

    if len(resolved_segments) < 2:
        reason = unavailable_reason or (
            "Fewer than two comparable operating segment disclosures were available."
        )
        return ValidationResult(
            rule_name="segment_revenue",
            metric_name="Segment Revenue Reconciliation",
            status="NOT_APPLICABLE",
            explanation=f"Segment revenue reconciliation is not applicable: {reason}",
            input_metric_refs=refs,
            affected_metrics=[],
        )

    # Check unit and period comparability across supplied segments
    for seg in resolved_segments:
        if seg.reported_unit != consolidated_revenue.reported_unit or seg.currency != consolidated_revenue.currency:
            return ValidationResult(
                rule_name="segment_revenue",
                metric_name="Segment Revenue Reconciliation",
                status="NOT_APPLICABLE",
                explanation=(
                    f"Segment '{seg.segment_name}' unit/currency ({seg.reported_unit}/{seg.currency}) "
                    f"is not comparable with consolidated Revenue "
                    f"({consolidated_revenue.reported_unit}/{consolidated_revenue.currency})."
                ),
                input_metric_refs=refs,
                affected_metrics=[],
            )
        if consolidated_revenue.period_end and seg.period_end and seg.period_end != consolidated_revenue.period_end:
            return ValidationResult(
                rule_name="segment_revenue",
                metric_name="Segment Revenue Reconciliation",
                status="NOT_APPLICABLE",
                explanation=(
                    f"Segment '{seg.segment_name}' period_end ({seg.period_end}) does not match "
                    f"consolidated Revenue period_end ({consolidated_revenue.period_end})."
                ),
                input_metric_refs=refs,
                affected_metrics=[],
            )
        refs.append(
            {
                "role": "segment",
                "metric_name": f"Segment:{seg.segment_name}",
                "xbrl_concept": seg.concept,
                "normalized_value": str(seg.value),
                "unit": seg.reported_unit,
                "currency": seg.currency,
                "period_start": seg.period_start,
                "period_end": seg.period_end,
                "source_location": seg.source_location,
            }
        )

    seg_total = sum((seg.value for seg in resolved_segments), Decimal(0))
    cons_rev = consolidated_revenue.normalized_value
    abs_diff = abs(seg_total - cons_rev)
    rel_diff = abs_diff / abs(cons_rev)
    tol = Decimal(str(val_settings.segment_reconciliation_tolerance))
    tol_desc = f"{tol:.2%} of Consolidated Revenue"

    if rel_diff <= tol:
        return ValidationResult(
            rule_name="segment_revenue",
            metric_name="Segment Revenue Reconciliation",
            status="PASS",
            explanation=(
                f"Sum of {len(resolved_segments)} comparable segments ({_fmt_money(seg_total)}) "
                f"reconciles with consolidated Revenue ({_fmt_money(cons_rev)}) within {tol:.2%} "
                f"tolerance (variance {_fmt_money(abs_diff)}, {rel_diff:.2%})."
            ),
            input_metric_refs=refs,
            affected_metrics=["Revenue"],
            expected_value=cons_rev,
            actual_value=seg_total,
            variance_abs=abs_diff,
            variance_pct=rel_diff,
            tolerance_used=tol_desc,
            escalate_to_review=False,
        )

    return ValidationResult(
        rule_name="segment_revenue",
        metric_name="Segment Revenue Reconciliation",
        status="FAIL",
        explanation=(
            f"Segment revenue reconciliation failure: sum of {len(resolved_segments)} disclosed "
            f"segments ({_fmt_money(seg_total)}) differs from consolidated Revenue ({_fmt_money(cons_rev)}) "
            f"by {_fmt_money(abs_diff)} ({rel_diff:.2%}), exceeding tolerance ({tol:.2%})."
        ),
        input_metric_refs=refs,
        affected_metrics=["Revenue"],
        expected_value=cons_rev,
        actual_value=seg_total,
        variance_abs=abs_diff,
        variance_pct=rel_diff,
        tolerance_used=tol_desc,
        escalate_to_review=True,
    )


def _find_prior_from_company_facts(
    record: ExtractedMetricRecord,
    metric_def: MetricDefinition | None,
    company_facts: dict[str, Any],
) -> PriorPeriodPoint | None:
    """Resolve the immediate prior annual fact from SEC Company Facts, detecting restatements."""
    us_gaap = company_facts.get("us-gaap", {}) if isinstance(company_facts, dict) else {}
    if not us_gaap or not record.period_end:
        return None

    current_end = _parse_date(record.period_end)
    if current_end is None:
        return None

    candidate_concepts: list[str] = []
    if record.xbrl_concept:
        candidate_concepts.append(record.xbrl_concept)
    if metric_def:
        for c in metric_def.xbrl_concepts:
            if c not in candidate_concepts:
                candidate_concepts.append(c)

    expected_kind = metric_def.period_type if metric_def else ("instant" if record.period_start is None else "duration")

    for concept in candidate_concepts:
        concept_obj = us_gaap.get(concept)
        if not isinstance(concept_obj, dict):
            continue
        units_map = concept_obj.get("units", {})
        if not isinstance(units_map, dict):
            continue

        by_end_date: dict[str, list[dict[str, Any]]] = {}
        for raw_unit_key, items in units_map.items():
            if not isinstance(items, list):
                continue
            unit_norm, currency = normalize_unit(raw_unit_key, fallback_unit=record.reported_unit)
            if unit_norm != record.reported_unit or currency != record.currency:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                form_str = str(item.get("form", "")).upper()
                if not form_str.startswith("10-K"):
                    continue
                p_start = item.get("start")
                p_end = item.get("end")
                p_end_date = _parse_date(p_end)
                if p_end_date is None or p_end_date >= current_end:
                    continue
                # Ignore facts older than ~20 months unless only wider gap (FY change) exists
                classification = classify_period(
                    start_date=p_start,
                    end_date=p_end,
                    fp=item.get("fp"),
                    frame=item.get("frame"),
                    expected_kind=expected_kind,
                )
                if not classification.is_annual:
                    continue
                parsed_val = parse_numeric_text(item.get("val"))
                if parsed_val is None:
                    continue
                by_end_date.setdefault(str(p_end), []).append(
                    {
                        "val": parsed_val,
                        "start": p_start,
                        "end": str(p_end),
                        "fy": item.get("fy"),
                        "accn": item.get("accn"),
                        "filed": str(item.get("filed") or ""),
                        "form": form_str,
                        "unit": unit_norm,
                        "currency": currency,
                    }
                )

        if not by_end_date:
            continue

        # Choose the closest prior annual end date strictly before current_end
        prior_end_str = max(by_end_date.keys())
        items_for_end = by_end_date[prior_end_str]

        # Sort chronologically by filed date ascending; keep current filing comparative column highest precedence
        items_sorted = sorted(
            items_for_end,
            key=lambda x: (
                1 if x["accn"] == record.accession_number else 0,
                x["filed"],
                str(x["accn"] or ""),
            ),
        )
        latest = items_sorted[-1]
        distinct_vals: list[Decimal] = []
        for it in items_sorted:
            if it["val"] not in distinct_vals:
                distinct_vals.append(it["val"])

        is_amended = any("/A" in it["form"] for it in items_sorted)
        restated = len(distinct_vals) > 1 or is_amended
        orig_val = distinct_vals[0] if len(distinct_vals) > 1 else None
        restatement_note = None
        if restated:
            if len(distinct_vals) > 1:
                restatement_note = (
                    f"Prior period {prior_end_str} reflects a restatement/revision in SEC filings "
                    f"(originally reported {_fmt_money(orig_val, record.reported_unit)}, "
                    f"revised to {_fmt_money(latest['val'], record.reported_unit)} as of {latest['filed'] or latest['accn']})."
                )
            else:
                restatement_note = (
                    f"Prior period {prior_end_str} includes amended 10-K/A filing ({latest['accn']})."
                )

        return PriorPeriodPoint(
            metric_name=record.metric_name,
            concept=concept,
            value=latest["val"],
            reported_unit=latest["unit"],
            currency=latest["currency"],
            period_start=latest["start"],
            period_end=latest["end"],
            fiscal_year=latest["fy"] if isinstance(latest["fy"], int) else None,
            accession_number=latest["accn"],
            filed_date=latest["filed"] or None,
            form_type=latest["form"],
            restated=restated,
            original_value=orig_val,
            restatement_note=restatement_note,
        )

    return None


def _build_prior_from_record(prior_rec: ExtractedMetricRecord) -> PriorPeriodPoint | None:
    if (
        prior_rec.extraction_status != "EXTRACTED"
        or prior_rec.normalized_value is None
        or not prior_rec.period_end
    ):
        return None
    return PriorPeriodPoint(
        metric_name=prior_rec.metric_name,
        concept=prior_rec.xbrl_concept,
        value=prior_rec.normalized_value,
        reported_unit=prior_rec.reported_unit,
        currency=prior_rec.currency,
        period_start=prior_rec.period_start,
        period_end=prior_rec.period_end,
        fiscal_year=prior_rec.fiscal_year,
        accession_number=prior_rec.accession_number,
        form_type=prior_rec.form_type,
    )


def validate_yoy_comparisons(
    records: list[ExtractedMetricRecord],
    *,
    company_facts: dict[str, Any] | None = None,
    prior_records: list[ExtractedMetricRecord] | dict[str, ExtractedMetricRecord] | None = None,
    prior_points: dict[str, PriorPeriodPoint] | None = None,
    settings: ValidationSettings | None = None,
) -> list[ValidationResult]:
    """Compare annual metric values year over year safely handling anomalies and edge cases."""
    val_settings = settings or get_settings().validation
    threshold = Decimal(str(val_settings.yoy_change_alert_threshold))
    tol_desc = f"±{threshold:.0%} YoY anomaly threshold"

    prior_rec_map: dict[str, ExtractedMetricRecord] = {}
    if isinstance(prior_records, dict):
        prior_rec_map = prior_records
    elif isinstance(prior_records, list):
        prior_rec_map = {r.metric_name: r for r in prior_records}

    results: list[ValidationResult] = []
    for rec in records:
        metric_def = get_metric_definition(rec.metric_name)
        refs: list[dict[str, Any]] = [_metric_ref(rec, "current_period")]

        if rec.extraction_status != "EXTRACTED" or rec.normalized_value is None:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="NOT_APPLICABLE",
                    explanation=(
                        f"YoY comparison for {rec.metric_name} is not applicable because the current "
                        f"period metric status is '{rec.extraction_status}'."
                    ),
                    input_metric_refs=refs,
                    tolerance_used=tol_desc,
                )
            )
            continue

        cur_end = _parse_date(rec.period_end)
        if cur_end is None:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="NOT_APPLICABLE",
                    explanation=(
                        f"YoY comparison for {rec.metric_name} is not applicable because current "
                        "period_end is missing or unparseable."
                    ),
                    input_metric_refs=refs,
                    tolerance_used=tol_desc,
                )
            )
            continue

        # Check current duration length (detect short/long transition fiscal year)
        cur_start = _parse_date(rec.period_start)
        expected_kind = metric_def.period_type if metric_def else ("instant" if rec.period_start is None else "duration")
        cur_days = (cur_end - cur_start).days if (cur_start and expected_kind == "duration") else None

        prior: PriorPeriodPoint | None = None
        if prior_points and rec.metric_name in prior_points:
            prior = prior_points[rec.metric_name]
        elif rec.metric_name in prior_rec_map:
            p_rec = prior_rec_map[rec.metric_name]
            prior = _build_prior_from_record(p_rec)
            if prior is None:
                refs.append(_metric_ref(p_rec, "prior_period"))
                results.append(
                    ValidationResult(
                        rule_name="yoy_comparison",
                        metric_name=rec.metric_name,
                        status="NOT_APPLICABLE",
                        explanation=(
                            f"YoY comparison for {rec.metric_name} is not applicable because prior "
                            f"period record status is '{p_rec.extraction_status}' or missing dates."
                        ),
                        input_metric_refs=refs,
                        tolerance_used=tol_desc,
                    )
                )
                continue
        elif company_facts:
            prior = _find_prior_from_company_facts(rec, metric_def, company_facts)

        if prior is None:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="NOT_APPLICABLE",
                    explanation=(
                        f"No comparable prior annual period found for {rec.metric_name} ending "
                        f"before {rec.period_end}; YoY check not applicable."
                    ),
                    input_metric_refs=refs,
                    tolerance_used=tol_desc,
                )
            )
            continue

        refs.append(
            {
                "role": "prior_period",
                "metric_name": prior.metric_name,
                "xbrl_concept": prior.concept,
                "normalized_value": str(prior.value),
                "unit": prior.reported_unit,
                "currency": prior.currency,
                "period_start": prior.period_start,
                "period_end": prior.period_end,
                "fiscal_year": prior.fiscal_year,
                "accession_number": prior.accession_number,
                "restated": prior.restated,
            }
        )

        # Non-comparable units / currencies check
        if prior.reported_unit != rec.reported_unit or prior.currency != rec.currency:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="NOT_APPLICABLE",
                    explanation=(
                        f"Non-comparable YoY units/currencies for {rec.metric_name}: "
                        f"current={rec.reported_unit}/{rec.currency} vs prior={prior.reported_unit}/{prior.currency}."
                    ),
                    input_metric_refs=refs,
                    tolerance_used=tol_desc,
                )
            )
            continue

        prior_end = _parse_date(prior.period_end)
        prior_start = _parse_date(prior.period_start)
        if prior_end is None or prior_end >= cur_end:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="NOT_APPLICABLE",
                    explanation=(
                        f"Non-comparable prior period end date ({prior.period_end}) relative to "
                        f"current period ({rec.period_end}) for {rec.metric_name}."
                    ),
                    input_metric_refs=refs,
                    tolerance_used=tol_desc,
                )
            )
            continue

        gap_days = (cur_end - prior_end).days
        prior_days = (prior_end - prior_start).days if (prior_start and expected_kind == "duration") else None

        # Detect fiscal-year change / non-standard transition period safely
        fy_change_reasons: list[str] = []
        if gap_days < 330 or gap_days > 400:
            fy_change_reasons.append(f"period ends are {gap_days} days apart ({prior.period_end} -> {rec.period_end})")
        if cur_days is not None and (cur_days < 345 or cur_days > 385):
            fy_change_reasons.append(f"current duration is {cur_days} days")
        if prior_days is not None and (prior_days < 345 or prior_days > 385):
            fy_change_reasons.append(f"prior duration is {prior_days} days")
        if cur_days is not None and prior_days is not None and abs(cur_days - prior_days) > 30:
            fy_change_reasons.append(f"duration changed from {prior_days}d to {cur_days}d")

        cur_val = rec.normalized_value
        prev_val = prior.value
        abs_diff = cur_val - prev_val

        if fy_change_reasons:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="WARNING",
                    explanation=(
                        f"Fiscal-year / period-length change detected for {rec.metric_name} ("
                        + "; ".join(fy_change_reasons)
                        + f"). Raw change from {_fmt_money(prev_val, rec.reported_unit)} to "
                        f"{_fmt_money(cur_val, rec.reported_unit)} ({_fmt_money(abs_diff, rec.reported_unit)}) "
                        "may be non-comparable without calendarization."
                    ),
                    input_metric_refs=refs,
                    affected_metrics=[rec.metric_name],
                    expected_value=prev_val,
                    actual_value=cur_val,
                    variance_abs=abs_diff,
                    variance_pct=None,
                    tolerance_used=tol_desc,
                    escalate_to_review=False,
                )
            )
            continue

        # Zero prior baseline handling
        if prev_val == Decimal(0):
            if cur_val == Decimal(0):
                results.append(
                    ValidationResult(
                        rule_name="yoy_comparison",
                        metric_name=rec.metric_name,
                        status="PASS",
                        explanation=(
                            f"{rec.metric_name} remained at {_fmt_money(Decimal(0), rec.reported_unit)} "
                            f"from {prior.period_end} to {rec.period_end} (0.0% change)."
                        ),
                        input_metric_refs=refs,
                        affected_metrics=[rec.metric_name],
                        expected_value=prev_val,
                        actual_value=cur_val,
                        variance_abs=Decimal(0),
                        variance_pct=Decimal(0),
                        tolerance_used=tol_desc,
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        rule_name="yoy_comparison",
                        metric_name=rec.metric_name,
                        status="WARNING",
                        explanation=(
                            f"Prior annual period ({prior.period_end}) value for {rec.metric_name} is 0, "
                            f"so relative YoY % variance is undefined (current {_fmt_money(cur_val, rec.reported_unit)}, "
                            f"absolute change {_fmt_money(abs_diff, rec.reported_unit)})."
                        ),
                        input_metric_refs=refs,
                        affected_metrics=[rec.metric_name],
                        expected_value=prev_val,
                        actual_value=cur_val,
                        variance_abs=abs_diff,
                        variance_pct=None,
                        tolerance_used=tol_desc,
                    )
                )
            continue

        # Safe denominator with abs(prev_val) for negative prior numbers
        pct_change = abs_diff / abs(prev_val)
        sign_flip = (prev_val < Decimal(0) and cur_val > Decimal(0)) or (
            prev_val > Decimal(0) and cur_val < Decimal(0)
        )
        exceeds_threshold = abs(pct_change) > threshold

        caveats: list[str] = []
        if prior.restated and prior.restatement_note:
            caveats.append(prior.restatement_note)
        if sign_flip:
            caveats.append(
                f"Sign reversal detected ({_fmt_money(prev_val, rec.reported_unit)} -> "
                f"{_fmt_money(cur_val, rec.reported_unit)})"
            )
        if exceeds_threshold:
            caveats.append(
                f"YoY change of {pct_change:+.1%} (vs |prior|) exceeds {threshold:.0%} anomaly threshold"
            )

        neg_note = " (computed against |prior| because prior period was negative)" if prev_val < Decimal(0) else ""
        base_summary = (
            f"{rec.metric_name} changed from {_fmt_money(prev_val, rec.reported_unit)} ({prior.period_end}) "
            f"to {_fmt_money(cur_val, rec.reported_unit)} ({rec.period_end}): "
            f"{_fmt_money(abs_diff, rec.reported_unit)} ({pct_change:+.1%}{neg_note})."
        )

        if caveats:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="WARNING",
                    explanation=f"{base_summary} {' '.join(caveats)}",
                    input_metric_refs=refs,
                    affected_metrics=[rec.metric_name],
                    expected_value=prev_val,
                    actual_value=cur_val,
                    variance_abs=abs_diff,
                    variance_pct=pct_change,
                    tolerance_used=tol_desc,
                    escalate_to_review=False,
                )
            )
        else:
            results.append(
                ValidationResult(
                    rule_name="yoy_comparison",
                    metric_name=rec.metric_name,
                    status="PASS",
                    explanation=f"{base_summary} Within {threshold:.0%} threshold.",
                    input_metric_refs=refs,
                    affected_metrics=[rec.metric_name],
                    expected_value=prev_val,
                    actual_value=cur_val,
                    variance_abs=abs_diff,
                    variance_pct=pct_change,
                    tolerance_used=tol_desc,
                    escalate_to_review=False,
                )
            )

    return results


def _merge_metric_validation_statuses(
    records: list[ExtractedMetricRecord],
    validations: list[ValidationResult],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Compute final per-metric validation_status and build escalation tasks for FAIL results."""
    precedence = {"FAIL": 4, "WARNING": 3, "PASS": 2, "NOT_APPLICABLE": 1}
    best_by_metric: dict[str, str] = {}
    failures_by_metric: dict[str, list[ValidationResult]] = {}

    for val in validations:
        for metric_name in val.affected_metrics:
            cur = best_by_metric.get(metric_name)
            if cur is None or precedence[val.status] > precedence[cur]:
                best_by_metric[metric_name] = val.status
            if val.status == "FAIL":
                failures_by_metric.setdefault(metric_name, []).append(val)

    # Metrics touched only as un-affected NOT_APPLICABLE keep their extraction-level status or NOT_APPLICABLE
    final_statuses: dict[str, str] = {}
    failure_escalations: list[dict[str, Any]] = []

    for rec in records:
        if rec.metric_name in best_by_metric:
            status = best_by_metric[rec.metric_name]
        elif rec.extraction_status != "EXTRACTED":
            status = rec.extraction_status
        else:
            status = "NOT_APPLICABLE"

        final_statuses[rec.metric_name] = status
        rec.validation_status = status

        if status == "FAIL":
            rec.review_status = "REVIEW_REQUIRED"
            for fail_res in failures_by_metric.get(rec.metric_name, []):
                failure_escalations.append(
                    {
                        "metric_name": rec.metric_name,
                        "reason": f"[Validation FAIL] {fail_res.rule_name}: {fail_res.explanation}",
                        "created_at": fail_res.evaluated_at,
                    }
                )

    return final_statuses, failure_escalations


def run_financial_validations(
    records: list[ExtractedMetricRecord],
    *,
    cik: str | None = None,
    ticker: str | None = None,
    accession_number: str | None = None,
    company_facts: dict[str, Any] | None = None,
    html_text: str | None = None,
    parsed_html: ParsedFilingHtml | None = None,
    segment_items: list[SegmentRevenueItem] | None = None,
    prior_records: list[ExtractedMetricRecord] | dict[str, ExtractedMetricRecord] | None = None,
    prior_points: dict[str, PriorPeriodPoint] | None = None,
    settings: ValidationSettings | None = None,
    persist: bool = True,
    run_id: str | None = None,
    db_path: Path | str | None = None,
) -> list[ValidationResult]:
    """Execute accounting equation, segment reconciliation, and YoY validations and optionally persist."""
    val_settings = settings or get_settings().validation
    resolved_html = parsed_html if parsed_html is not None else (parse_filing_html(html_text) if html_text else None)

    by_name = {r.metric_name: r for r in records}
    resolved_cik = cik or (records[0].cik if records else "")
    resolved_ticker = ticker or (records[0].ticker if records else None)
    resolved_accn = accession_number or (records[0].accession_number if records else "")

    validations: list[ValidationResult] = [
        validate_accounting_equation(records, settings=val_settings),
        validate_segment_revenue(
            by_name.get("Revenue"),
            parsed_html=resolved_html,
            segment_items=segment_items,
            settings=val_settings,
        ),
        *validate_yoy_comparisons(
            records,
            company_facts=company_facts,
            prior_records=prior_records,
            prior_points=prior_points,
            settings=val_settings,
        ),
    ]

    final_statuses, failure_escalations = _merge_metric_validation_statuses(records, validations)

    if persist and resolved_cik and resolved_accn:
        init_db(db_path)
        with get_connection(db_path) as conn:
            filing_row = conn.execute(
                "SELECT id, company_name FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
                (resolved_cik, resolved_accn),
            ).fetchone()
            filing_id = int(filing_row["id"]) if filing_row else None
            company_name = filing_row["company_name"] if filing_row else None
            save_validation_results(
                results=[
                    v.to_db_row(
                        cik=resolved_cik,
                        ticker=resolved_ticker,
                        accession_number=resolved_accn,
                        run_id=run_id,
                    )
                    for v in validations
                ],
                cik=resolved_cik,
                accession_number=resolved_accn,
                db_path=db_path,
                conn=conn,
            )
            created_tasks = apply_validation_outcomes_to_filing(
                cik=resolved_cik,
                ticker=resolved_ticker,
                accession_number=resolved_accn,
                metric_validation_statuses=final_statuses,
                failure_escalations=failure_escalations,
                run_id=run_id,
                db_path=db_path,
                conn=conn,
            )
            counts = {
                st: sum(1 for v in validations if v.status == st)
                for st in ("PASS", "FAIL", "WARNING", "NOT_APPLICABLE")
            }
            record_audit_event(
                event_type="VALIDATIONS_COMPLETED",
                actor="validator",
                run_id=run_id,
                cik=resolved_cik,
                ticker=resolved_ticker,
                company_name=company_name,
                filing_id=filing_id,
                accession_number=resolved_accn,
                decision="VALIDATIONS_COMPLETED",
                explanation=(
                    f"PASS={counts['PASS']}, FAIL={counts['FAIL']}, "
                    f"WARNING={counts['WARNING']}, NOT_APPLICABLE={counts['NOT_APPLICABLE']}."
                ),
                payload={
                    "cik": resolved_cik,
                    "ticker": resolved_ticker,
                    "company_name": company_name,
                    "filing_id": filing_id,
                    "accession_number": resolved_accn,
                    "counts": counts,
                    "escalated_failures": created_tasks,
                },
                conn=conn,
            )
            if failure_escalations:
                record_audit_event(
                    event_type="VALIDATION_FAILURES_ESCALATED",
                    actor="validator",
                    run_id=run_id,
                    cik=resolved_cik,
                    ticker=resolved_ticker,
                    company_name=company_name,
                    filing_id=filing_id,
                    accession_number=resolved_accn,
                    decision="ESCALATED",
                    explanation=f"Escalated {created_tasks} task(s) from failed validation rules.",
                    payload={
                        "cik": resolved_cik,
                        "ticker": resolved_ticker,
                        "company_name": company_name,
                        "filing_id": filing_id,
                        "accession_number": resolved_accn,
                        "failed_metrics": sorted({item["metric_name"] for item in failure_escalations}),
                        "review_tasks_created": created_tasks,
                    },
                    conn=conn,
                )

    return validations
