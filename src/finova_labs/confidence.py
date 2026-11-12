"""Explainable confidence-scoring engine for FinovaLabs extracted metrics."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from finova_labs.metric_mapping import MetricDefinition, get_metric_definition
from finova_labs.normalization import classify_period
from finova_labs.settings import ConfidenceSettings, get_settings

if TYPE_CHECKING:
    from finova_labs.extractor import CandidateFact, ExtractedMetricRecord

SCORING_METHOD_DOC = """
FinovaLabs Confidence Scoring Method (Additive Weighted Model):
- Five configurable factors with weights summing to 1.00:
  1. Label / Concept Match (default 25%): Verifies alignment with approved US-GAAP concepts and absence of unresolved candidate conflicts.
  2. Reporting Period Match (default 25%): Verifies annual period classification (duration ~330-385d or balance-sheet instant), fiscal period 'FY', and alignment to the target filing period end date.
  3. Unit & Scale Correctness (default 20%): Verifies expected unit ('USD' or 'USD/shares'), currency match, valid scale factor, and sign convention ('positive' vs 'signed').
  4. Evidence Quality (default 20%): Verifies presence of a verbatim/structured snippet, traceable filing/section location, and SEC source URL.
  5. Independent-Path Agreement (default 10%): Verifies whether SEC Company Facts XBRL and 10-K Inline XBRL HTML independently corroborate the extracted value.
- Unavailable Factor Rule: Any factor that cannot be evaluated (such as independent cross-path confirmation when only one source path is available, or unit/scale checks for missing facts) is marked UNAVAILABLE with raw_score=None and contributes 0.00. Unavailable factors are never treated as passing.
- Escalation Policy: Any metric scoring strictly below auto_approve_threshold (default 0.90) or having non-EXTRACTED status (AMBIGUOUS / MISSING) is escalated to Human Review (REVIEW_REQUIRED).
""".strip()


class FactorScore(BaseModel):
    """Score and human-readable rationale for one confidence factor."""

    factor: str
    label: str
    weight: float
    available: bool
    raw_score: float | None = None
    contribution: float = 0.0
    status: str  # PASS | PARTIAL | FAIL | UNAVAILABLE
    reason: str


class ConfidenceAssessment(BaseModel):
    """Complete explainable confidence scoring result for an extracted metric."""

    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    scoring_version: str
    decision: str  # AUTO_APPROVED | REVIEW_REQUIRED
    escalated_to_review: bool
    reasons: list[str]
    explanation: str
    factors: list[FactorScore]
    available_weight: float
    unavailable_factors: list[str]
    method_summary: str = SCORING_METHOD_DOC

    def components_dict(self) -> dict[str, Any]:
        """Serialize component factor breakdown and scoring metadata for SQLite storage."""
        return {
            "scoring_version": self.scoring_version,
            "threshold": self.threshold,
            "score": self.score,
            "decision": self.decision,
            "available_weight": self.available_weight,
            "unavailable_factors": self.unavailable_factors,
            "factors": [f.model_dump() for f in self.factors],
            "method_summary": self.method_summary,
        }

    def components_json(self) -> str:
        """Return compact JSON representation of the component factor breakdown."""
        return json.dumps(self.components_dict())


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _factor_status(available: bool, raw_score: float | None) -> str:
    if not available or raw_score is None:
        return "UNAVAILABLE"
    if raw_score >= 0.85:
        return "PASS"
    if raw_score >= 0.45:
        return "PARTIAL"
    return "FAIL"


def _make_factor(
    factor: str,
    label: str,
    weight: float,
    available: bool,
    raw_score: float | None,
    reason: str,
) -> FactorScore:
    if not available or raw_score is None:
        return FactorScore(
            factor=factor,
            label=label,
            weight=weight,
            available=False,
            raw_score=None,
            contribution=0.0,
            status="UNAVAILABLE",
            reason=reason,
        )
    clamped = max(0.0, min(1.0, float(raw_score)))
    return FactorScore(
        factor=factor,
        label=label,
        weight=weight,
        available=True,
        raw_score=round(clamped, 4),
        contribution=round(weight * clamped, 6),
        status=_factor_status(True, clamped),
        reason=reason,
    )


def _best_candidate_source(candidates: list[CandidateFact], normalized_value: Decimal | None) -> str | None:
    if not candidates:
        return None
    matching = [
        c for c in candidates
        if normalized_value is None or c.normalized_value == normalized_value
    ]
    pool = matching or candidates
    sources = {c.source for c in pool}
    if "xbrl+html" in sources:
        return "xbrl+html"
    if any("xbrl" in s for s in sources) and any("html" in s for s in sources):
        return "xbrl+html"
    if "html" in sources:
        return "html"
    return pool[0].source


def _score_label_concept_match(
    record: ExtractedMetricRecord,
    metric_def: MetricDefinition | None,
    weight: float,
) -> FactorScore:
    status = record.extraction_status.upper()
    if status == "MISSING" or not record.xbrl_concept:
        return _make_factor(
            "label_concept_match",
            "Label / Concept Match",
            weight,
            True,
            0.0,
            f"No approved US-GAAP concept matched for '{record.metric_name}'.",
        )

    if status == "AMBIGUOUS":
        distinct_count = len({c.normalized_value for c in record.candidates}) if record.candidates else 2
        return _make_factor(
            "label_concept_match",
            "Label / Concept Match",
            weight,
            True,
            0.30,
            (
                f"Matched concept 'us-gaap:{record.xbrl_concept}', but {distinct_count} conflicting "
                f"candidate values were found at top priority rank."
            ),
        )

    approved_concepts = metric_def.xbrl_concepts if metric_def else ()
    if record.xbrl_concept in approved_concepts:
        rank = approved_concepts.index(record.xbrl_concept)
        if rank == 0:
            raw = 1.0
        elif rank == 1:
            raw = 0.95
        else:
            raw = max(0.75, 1.0 - 0.05 * rank)
        return _make_factor(
            "label_concept_match",
            "Label / Concept Match",
            weight,
            True,
            raw,
            f"Exact match to approved concept 'us-gaap:{record.xbrl_concept}' (mapping priority #{rank + 1}).",
        )

    return _make_factor(
        "label_concept_match",
        "Label / Concept Match",
        weight,
        True,
        0.50,
        f"Concept 'us-gaap:{record.xbrl_concept}' is not in the primary approved mapping list.",
    )


def _score_reporting_period_match(
    record: ExtractedMetricRecord,
    metric_def: MetricDefinition | None,
    filing_reporting_period: str | None,
    weight: float,
) -> FactorScore:
    if record.extraction_status.upper() == "MISSING":
        return _make_factor(
            "reporting_period_match",
            "Reporting Period Match",
            weight,
            True,
            0.0,
            "No reporting period verified because no fact was extracted.",
        )

    if not record.period_end:
        return _make_factor(
            "reporting_period_match",
            "Reporting Period Match",
            weight,
            False,
            None,
            "Reporting period end date is unavailable on the extracted record (0.00 contribution).",
        )

    expected_kind = metric_def.period_type if metric_def else ("instant" if record.period_start is None else "duration")
    classification = classify_period(
        start_date=record.period_start,
        end_date=record.period_end,
        fp=record.fiscal_period,
        expected_kind=expected_kind,
    )

    if not classification.is_annual:
        return _make_factor(
            "reporting_period_match",
            "Reporting Period Match",
            weight,
            True,
            0.15,
            (
                f"Period '{record.period_start or 'instant'} -> {record.period_end}' classified as "
                f"'{classification.period_kind}', failing the annual 10-K period requirement."
            ),
        )

    fp_upper = (record.fiscal_period or "").upper()
    if fp_upper and fp_upper != "FY":
        return _make_factor(
            "reporting_period_match",
            "Reporting Period Match",
            weight,
            True,
            0.25,
            f"Fiscal period '{record.fiscal_period}' is not annual 'FY'.",
        )

    target_date = _parse_iso_date(filing_reporting_period)
    fact_date = _parse_iso_date(record.period_end)
    if target_date and fact_date:
        day_diff = abs((target_date - fact_date).days)
        if day_diff <= 7:
            return _make_factor(
                "reporting_period_match",
                "Reporting Period Match",
                weight,
                True,
                1.0,
                f"Annual {expected_kind} period ending {record.period_end} aligns with filing period {filing_reporting_period}.",
            )
        if day_diff <= 45:
            return _make_factor(
                "reporting_period_match",
                "Reporting Period Match",
                weight,
                True,
                0.70,
                f"Annual period ending {record.period_end} differs by {day_diff} days from filing period {filing_reporting_period}.",
            )
        return _make_factor(
            "reporting_period_match",
            "Reporting Period Match",
            weight,
            True,
            0.35,
            f"Annual period ending {record.period_end} is {day_diff} days off from filing period {filing_reporting_period}.",
        )

    return _make_factor(
        "reporting_period_match",
        "Reporting Period Match",
        weight,
        True,
        0.95,
        f"Annual {expected_kind} period ending {record.period_end} verified (filing target date not supplied for delta check).",
    )


def _score_unit_scale_correctness(
    record: ExtractedMetricRecord,
    metric_def: MetricDefinition | None,
    weight: float,
) -> FactorScore:
    status = record.extraction_status.upper()
    if status == "MISSING":
        return _make_factor(
            "unit_scale_correctness",
            "Unit & Scale Correctness",
            weight,
            False,
            None,
            "Unit and scale check unavailable because no numeric fact was extracted (0.00 contribution).",
        )

    if record.normalized_value is None:
        if status == "AMBIGUOUS" and record.candidates:
            expected_unit = metric_def.expected_unit if metric_def else record.reported_unit
            all_match = all(c.reported_unit == expected_unit and c.scale_factor >= 1 for c in record.candidates)
            raw = 0.70 if all_match else 0.35
            return _make_factor(
                "unit_scale_correctness",
                "Unit & Scale Correctness",
                weight,
                True,
                raw,
                f"No single normalized value selected due to ambiguity; candidate units match '{expected_unit}': {all_match}.",
            )
        return _make_factor(
            "unit_scale_correctness",
            "Unit & Scale Correctness",
            weight,
            False,
            None,
            "Normalized numeric value is unavailable for unit/scale verification (0.00 contribution).",
        )

    raw = 1.0
    issues: list[str] = []

    expected_unit = metric_def.expected_unit if metric_def else record.reported_unit
    expected_currency = metric_def.currency if metric_def else record.currency
    if not record.reported_unit or record.reported_unit != expected_unit:
        raw -= 0.50
        issues.append(f"unit '{record.reported_unit}' != expected '{expected_unit}'")

    if expected_currency and record.currency != expected_currency:
        raw -= 0.20
        issues.append(f"currency '{record.currency}' != expected '{expected_currency}'")

    if record.scale_factor is None or record.scale_factor < 1:
        raw -= 0.25
        issues.append(f"invalid scale_factor '{record.scale_factor}'")

    if metric_def and metric_def.sign_convention == "positive" and record.normalized_value < Decimal(0):
        raw -= 0.35
        issues.append(f"negative value {record.normalized_value} violates positive sign convention")

    raw = max(0.0, min(1.0, raw))
    if not issues:
        return _make_factor(
            "unit_scale_correctness",
            "Unit & Scale Correctness",
            weight,
            True,
            raw,
            (
                f"Unit '{record.reported_unit}' ({record.currency}) and scale {record.scale_factor}x "
                f"match specification and sign convention."
            ),
        )

    return _make_factor(
        "unit_scale_correctness",
        "Unit & Scale Correctness",
        weight,
        True,
        raw,
        "Unit/scale validation warning: " + "; ".join(issues) + ".",
    )


def _score_evidence_quality(
    record: ExtractedMetricRecord,
    weight: float,
) -> FactorScore:
    snippet = (record.evidence_snippet or "").strip()
    location = (record.evidence_location or "").strip()
    source_url = (record.source_url or "").strip()

    if record.extraction_status.upper() == "MISSING" or not snippet or snippet.lower().startswith("no annual 10-k fact found"):
        return _make_factor(
            "evidence_quality",
            "Evidence Quality",
            weight,
            True,
            0.0,
            "No verbatim or structured source evidence snippet captured for this metric.",
        )

    best_source = _best_candidate_source(record.candidates, record.normalized_value)
    if best_source == "xbrl+html":
        base = 1.0
        source_desc = "Dual HTML filing anchor and SEC Company Facts evidence"
    elif best_source == "html":
        base = 0.90
        source_desc = "10-K HTML inline/table evidence snippet"
    elif best_source == "xbrl":
        base = 0.85
        source_desc = "SEC Company Facts JSON reference without HTML table anchor"
    else:
        base = 0.75
        source_desc = "Recorded extraction evidence"

    deductions: list[str] = []
    if len(snippet) < 10:
        base -= 0.35
        deductions.append("brief snippet")
    if not location:
        base -= 0.25
        deductions.append("missing evidence location")
    if not source_url or not source_url.startswith("http"):
        base -= 0.20
        deductions.append("missing SEC source URL")

    if record.extraction_status.upper() == "AMBIGUOUS":
        base = min(base, 0.60)
        deductions.append("ambiguous candidate evidence")

    raw = max(0.0, min(1.0, base))
    detail = f"{source_desc} at '{location}'" if location else source_desc
    if deductions:
        detail += " (penalties: " + ", ".join(deductions) + ")"
    return _make_factor(
        "evidence_quality",
        "Evidence Quality",
        weight,
        True,
        raw,
        detail + ".",
    )


def _score_independent_path_agreement(
    record: ExtractedMetricRecord,
    html_checked: bool | None,
    weight: float,
) -> FactorScore:
    status = record.extraction_status.upper()
    if status == "MISSING":
        return _make_factor(
            "independent_path_agreement",
            "Independent-Path Agreement",
            weight,
            False,
            None,
            "Independent cross-path check unavailable because no fact was extracted (0.00 contribution).",
        )

    if status == "AMBIGUOUS":
        return _make_factor(
            "independent_path_agreement",
            "Independent-Path Agreement",
            weight,
            True,
            0.0,
            "Candidate facts disagree across values; independent agreement failed.",
        )

    matching_candidates = [
        c for c in record.candidates
        if record.normalized_value is None or c.normalized_value == record.normalized_value
    ]
    sources = {c.source for c in matching_candidates}

    has_xbrl_and_html = (
        "xbrl+html" in sources
        or (any("xbrl" in s for s in sources) and any("html" in s for s in sources))
    )
    if has_xbrl_and_html:
        return _make_factor(
            "independent_path_agreement",
            "Independent-Path Agreement",
            weight,
            True,
            1.0,
            "SEC Company Facts XBRL and 10-K Inline XBRL HTML independently agree on the extracted value.",
        )

    distinct_html_conflict = any(
        "html" in c.source and record.normalized_value is not None and c.normalized_value != record.normalized_value
        for c in record.candidates
    )
    if distinct_html_conflict:
        return _make_factor(
            "independent_path_agreement",
            "Independent-Path Agreement",
            weight,
            True,
            0.0,
            "HTML candidate value disagrees with the selected XBRL fact.",
        )

    mode_note = (
        "10-K HTML was checked but no matching Inline XBRL confirmation was found"
        if html_checked is True
        else "only a single extraction path was available"
    )
    return _make_factor(
        "independent_path_agreement",
        "Independent-Path Agreement",
        weight,
        False,
        None,
        (
            f"Independent cross-path verification unavailable ({mode_note}); "
            "unavailable factor contributes 0.00 and is not assumed to pass."
        ),
    )


def score_extracted_metric(
    record: ExtractedMetricRecord,
    *,
    metric_def: MetricDefinition | None = None,
    filing_reporting_period: str | None = None,
    html_checked: bool | None = None,
    settings: ConfidenceSettings | None = None,
) -> ConfidenceAssessment:
    """Compute an explainable confidence score in [0, 1] and review routing decision."""
    conf_settings = settings or get_settings().confidence
    weights = conf_settings.weights
    resolved_def = metric_def or get_metric_definition(record.metric_name)

    factors = [
        _score_label_concept_match(record, resolved_def, weights.label_concept_match),
        _score_reporting_period_match(record, resolved_def, filing_reporting_period, weights.reporting_period_match),
        _score_unit_scale_correctness(record, resolved_def, weights.unit_scale_correctness),
        _score_evidence_quality(record, weights.evidence_quality),
        _score_independent_path_agreement(record, html_checked, weights.independent_path_agreement),
    ]

    total_score = sum(f.contribution for f in factors)
    clamped_score = round(max(0.0, min(1.0, total_score)), 4)
    available_weight = round(sum(f.weight for f in factors if f.available), 4)
    unavailable_factors = [f.factor for f in factors if not f.available]

    threshold = float(conf_settings.auto_approve_threshold)
    is_extracted = record.extraction_status.upper() == "EXTRACTED"
    escalate = (not is_extracted) or (clamped_score < threshold)
    decision = "REVIEW_REQUIRED" if escalate else "AUTO_APPROVED"

    reasons = [f"[{f.status}] {f.label} ({f.weight:.0%}): {f.reason}" for f in factors]
    if not is_extracted:
        reasons.append(
            f"Escalated to human review because extraction status is '{record.extraction_status}' "
            f"(score {clamped_score:.2f}, threshold {threshold:.2f})."
        )
    elif clamped_score < threshold:
        reasons.append(
            f"Escalated to human review because confidence score {clamped_score:.2f} "
            f"is below approval threshold {threshold:.2f}."
        )
    else:
        reasons.append(
            f"Auto-approved because confidence score {clamped_score:.2f} meets or exceeds "
            f"threshold {threshold:.2f}."
        )

    return ConfidenceAssessment(
        score=clamped_score,
        threshold=threshold,
        scoring_version=conf_settings.scoring_version,
        decision=decision,
        escalated_to_review=escalate,
        reasons=reasons,
        explanation=" | ".join(reasons),
        factors=factors,
        available_weight=available_weight,
        unavailable_factors=unavailable_factors,
    )


def score_extracted_metrics(
    records: list[ExtractedMetricRecord],
    *,
    filing_reporting_period: str | None = None,
    html_checked: bool | None = None,
    settings: ConfidenceSettings | None = None,
) -> list[ConfidenceAssessment]:
    """Score a sequence of extracted metric records using shared confidence configuration."""
    conf_settings = settings or get_settings().confidence
    return [
        score_extracted_metric(
            record,
            filing_reporting_period=filing_reporting_period,
            html_checked=html_checked,
            settings=conf_settings,
        )
        for record in records
    ]
