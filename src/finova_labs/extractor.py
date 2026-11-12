"""Candidate metric extraction and supporting source evidence capture for FinovaLabs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from finova_labs.audit import record_audit_event
from finova_labs.confidence import score_extracted_metric
from finova_labs.database import (
    get_connection,
    init_db,
    save_extracted_metrics,
    sync_review_tasks_for_filing,
)
from finova_labs.filing_parser import HtmlFactEvidence, ParsedFilingHtml, parse_filing_html
from finova_labs.logging_config import get_logger
from finova_labs.metric_mapping import MetricDefinition, get_approved_metrics
from finova_labs.normalization import classify_period, normalize_unit, parse_numeric_text
from finova_labs.sec_client import FilingMetadata, SecEdgarClient
from finova_labs.settings import ConfidenceSettings, ValidationSettings
from finova_labs.validators import run_financial_validations

logger = get_logger("extractor")


class CandidateFact(BaseModel):
    """Single candidate fact discovered in SEC Company Facts and/or 10-K HTML."""

    concept: str
    rank: int
    raw_value: str
    normalized_value: Decimal
    reported_unit: str
    currency: str
    scale_factor: Decimal = Decimal(1)
    fiscal_period: str = "FY"
    fiscal_year: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    source: str
    evidence_snippet: str
    evidence_location: str


class ExtractedMetricRecord(BaseModel):
    """Final extraction outcome for one approved financial metric."""

    cik: str
    ticker: str | None = None
    accession_number: str
    form_type: str = "10-K"
    metric_name: str
    xbrl_concept: str | None = None
    raw_value: str | None = None
    normalized_value: Decimal | None = None
    reported_unit: str
    currency: str
    scale_factor: Decimal = Decimal(1)
    fiscal_period: str = "FY"
    fiscal_year: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    source_url: str
    evidence_snippet: str
    evidence_location: str
    extraction_status: str  # EXTRACTED | AMBIGUOUS | MISSING
    review_status: str = "NOT_REQUIRED"
    validation_status: str = "PENDING"
    confidence_score: float | None = None
    confidence_components: dict[str, Any] | None = None
    confidence_reasons: list[str] = Field(default_factory=list)
    confidence_threshold: float | None = None
    scoring_version: str | None = None
    confidence_explanation: str = ""
    candidates: list[CandidateFact] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_row(self, run_id: str | None = None) -> dict[str, Any]:
        """Convert to a SQLite-ready dictionary preserving Decimal precision."""
        return {
            "run_id": run_id,
            "cik": self.cik,
            "ticker": self.ticker,
            "accession_number": self.accession_number,
            "form_type": self.form_type,
            "metric_name": self.metric_name,
            "xbrl_concept": self.xbrl_concept,
            "raw_value": self.raw_value,
            "normalized_value": float(self.normalized_value)
            if self.normalized_value is not None
            else None,
            "normalized_decimal": str(self.normalized_value)
            if self.normalized_value is not None
            else None,
            "unit": self.reported_unit,
            "currency": self.currency,
            "scale_factor": float(self.scale_factor)
            if self.scale_factor != self.scale_factor.to_integral_value()
            else int(self.scale_factor),
            "fiscal_period": self.fiscal_period,
            "fiscal_year": self.fiscal_year,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "source_url": self.source_url,
            "source_evidence": self.evidence_snippet,
            "evidence_location": self.evidence_location,
            "extraction_status": self.extraction_status,
            "candidates_json": json.dumps(
                [c.model_dump(mode="json") for c in self.candidates],
                ensure_ascii=False,
            ),
            "confidence_score": self.confidence_score,
            "confidence_components_json": json.dumps(
                self.confidence_components,
                ensure_ascii=False,
            )
            if self.confidence_components is not None
            else None,
            "confidence_reasons": json.dumps(
                self.confidence_reasons,
                ensure_ascii=False,
            )
            if self.confidence_reasons
            else None,
            "confidence_threshold": self.confidence_threshold,
            "scoring_version": self.scoring_version,
            "validation_status": self.validation_status,
            "review_status": self.review_status,
            "created_at": self.created_at,
        }


def _match_html_evidence(
    parsed_html: ParsedFilingHtml | None,
    concept: str,
    target_value: Decimal,
    period_start: str | None,
    period_end: str | None,
) -> HtmlFactEvidence | None:
    """Find matching non-dimensional HTML Inline XBRL evidence for a Company Facts value."""
    if parsed_html is None:
        return None
    html_candidates = parsed_html.facts_by_concept.get(concept, [])
    if not html_candidates:
        return None

    for fact in html_candidates:
        if fact.has_dimensions:
            continue
        if fact.normalized_value != target_value:
            continue
        if period_end and fact.period_end and fact.period_end != period_end:
            continue
        if period_start and fact.period_start and fact.period_start != period_start:
            continue
        return fact
    return None


def _collect_xbrl_candidates(
    metric: MetricDefinition,
    filing: FilingMetadata,
    us_gaap: dict[str, Any],
    parsed_html: ParsedFilingHtml | None,
) -> list[CandidateFact]:
    """Collect valid annual/instant candidate facts from SEC Company Facts XBRL."""
    candidates: list[CandidateFact] = []
    target_end = filing.reporting_period

    for rank, concept in enumerate(metric.xbrl_concepts):
        concept_obj = us_gaap.get(concept)
        if not isinstance(concept_obj, dict):
            continue
        units_map = concept_obj.get("units")
        if not isinstance(units_map, dict):
            continue

        concept_matches: list[tuple[dict[str, Any], str, str, Decimal, str | None]] = []
        for raw_unit_key, items in units_map.items():
            if not isinstance(items, list):
                continue
            unit_norm, currency = normalize_unit(raw_unit_key, fallback_unit=metric.expected_unit)
            if unit_norm != metric.expected_unit:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("accn") != filing.accession_number:
                    continue
                if str(item.get("form", "")).upper() != filing.form_type.upper():
                    continue

                p_start = item.get("start")
                p_end = item.get("end")
                classification = classify_period(
                    start_date=p_start,
                    end_date=p_end,
                    fp=item.get("fp"),
                    frame=item.get("frame"),
                    expected_kind=metric.period_type,
                )
                if not classification.is_annual:
                    continue

                parsed_val = parse_numeric_text(item.get("val"))
                if parsed_val is None:
                    continue

                concept_matches.append(
                    (item, unit_norm, currency, parsed_val, classification.fiscal_period)
                )

        if not concept_matches:
            continue

        # Prefer items aligned to the filing's reporting_period; otherwise take latest annual end date.
        if target_end and any(m[0].get("end") == target_end for m in concept_matches):
            concept_matches = [m for m in concept_matches if m[0].get("end") == target_end]
        else:
            latest_end = max(str(m[0].get("end") or "") for m in concept_matches)
            concept_matches = [m for m in concept_matches if str(m[0].get("end") or "") == latest_end]

        for item, unit_norm, currency, parsed_val, fp_norm in concept_matches:
            p_start = item.get("start")
            p_end = item.get("end")
            fy_val = item.get("fy") if isinstance(item.get("fy"), int) else filing.fiscal_year

            html_hit = _match_html_evidence(
                parsed_html=parsed_html,
                concept=concept,
                target_value=parsed_val,
                period_start=p_start,
                period_end=p_end,
            )

            if html_hit is not None:
                raw_val = html_hit.raw_value
                scale_factor = html_hit.scale_factor
                source = "xbrl+html"
                snippet = html_hit.evidence_snippet
                location = html_hit.evidence_location
            else:
                raw_val = str(parsed_val)
                scale_factor = 1
                source = "xbrl"
                snippet = (
                    f"us-gaap:{concept} = {parsed_val} {unit_norm} "
                    f"(accn={filing.accession_number}, period={p_start or 'instant'}..{p_end})"
                )
                location = f"SEC CompanyFacts JSON (us-gaap:{concept})"

            candidates.append(
                CandidateFact(
                    concept=concept,
                    rank=rank,
                    raw_value=raw_val,
                    normalized_value=parsed_val,
                    reported_unit=unit_norm,
                    currency=currency,
                    scale_factor=scale_factor,
                    fiscal_period=fp_norm or "FY",
                    fiscal_year=fy_val,
                    period_start=p_start,
                    period_end=p_end,
                    source=source,
                    evidence_snippet=snippet,
                    evidence_location=location,
                )
            )

    return candidates


def _collect_html_fallback_candidates(
    metric: MetricDefinition,
    filing: FilingMetadata,
    parsed_html: ParsedFilingHtml | None,
) -> list[CandidateFact]:
    """Fallback to non-dimensional Inline XBRL HTML facts when Company Facts lacks a metric."""
    if parsed_html is None:
        return []

    candidates: list[CandidateFact] = []
    target_end = filing.reporting_period

    for rank, concept in enumerate(metric.xbrl_concepts):
        for fact in parsed_html.facts_by_concept.get(concept, []):
            if fact.has_dimensions:
                continue
            if fact.reported_unit != metric.expected_unit:
                continue
            classification = classify_period(
                start_date=fact.period_start,
                end_date=fact.period_end,
                fp="FY",
                expected_kind=metric.period_type,
            )
            if not classification.is_annual:
                continue
            if target_end and fact.period_end and fact.period_end != target_end:
                continue

            candidates.append(
                CandidateFact(
                    concept=concept,
                    rank=rank,
                    raw_value=fact.raw_value,
                    normalized_value=fact.normalized_value,
                    reported_unit=fact.reported_unit,
                    currency=fact.currency,
                    scale_factor=fact.scale_factor,
                    fiscal_period="FY",
                    fiscal_year=filing.fiscal_year,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    source="html",
                    evidence_snippet=fact.evidence_snippet,
                    evidence_location=fact.evidence_location,
                )
            )
    return candidates


def _deduplicate_candidates(candidates: list[CandidateFact]) -> list[CandidateFact]:
    """Deduplicate identical values at the same rank, preferring xbrl+html evidence."""
    best_by_key: dict[tuple[str, Decimal, str | None, str | None], CandidateFact] = {}
    for cand in candidates:
        key = (cand.concept, cand.normalized_value, cand.period_start, cand.period_end)
        existing = best_by_key.get(key)
        if existing is None or (existing.source != "xbrl+html" and cand.source == "xbrl+html"):
            best_by_key[key] = cand
    return list(best_by_key.values())


def extract_metrics_for_filing(
    filing: FilingMetadata,
    company_facts: dict[str, Any],
    html_text: str | None = None,
    metrics: tuple[MetricDefinition, ...] | None = None,
    persist: bool = True,
    run_id: str | None = None,
    db_path: Path | str | None = None,
    confidence_settings: ConfidenceSettings | None = None,
    validation_settings: ValidationSettings | None = None,
    run_validations: bool = True,
) -> list[ExtractedMetricRecord]:
    """Extract approved annual financial metrics from SEC Company Facts and 10-K HTML.

    Distinguishes annual periods from quarterly/YTD values, preserves Decimal
    precision and provenance, flags ambiguous candidate conflicts without
    silently picking a winner, and never fabricates missing metrics.
    """
    target_metrics = metrics or get_approved_metrics()
    us_gaap = company_facts.get("us-gaap", {}) if isinstance(company_facts, dict) else {}
    parsed_html = parse_filing_html(html_text) if html_text else None

    results: list[ExtractedMetricRecord] = []
    for metric in target_metrics:
        raw_candidates = _collect_xbrl_candidates(metric, filing, us_gaap, parsed_html)
        if not raw_candidates:
            raw_candidates = _collect_html_fallback_candidates(metric, filing, parsed_html)

        deduped = _deduplicate_candidates(raw_candidates)

        if not deduped:
            results.append(
                ExtractedMetricRecord(
                    cik=filing.cik,
                    ticker=filing.ticker,
                    accession_number=filing.accession_number,
                    form_type=filing.form_type,
                    metric_name=metric.name,
                    reported_unit=metric.expected_unit,
                    currency=metric.currency,
                    fiscal_period="FY",
                    fiscal_year=filing.fiscal_year,
                    period_end=filing.reporting_period,
                    source_url=filing.filing_url,
                    evidence_snippet=(
                        f"No annual 10-K fact found in Company Facts or HTML for "
                        f"concepts {', '.join(metric.xbrl_concepts)}."
                    ),
                    evidence_location=filing.companyfacts_url,
                    extraction_status="MISSING",
                    review_status="MISSING",
                    validation_status="MISSING",
                    candidates=[],
                )
            )
            continue

        top_rank = min(c.rank for c in deduped)
        top_candidates = [c for c in deduped if c.rank == top_rank]
        distinct_values = {c.normalized_value for c in top_candidates}

        if len(distinct_values) > 1:
            summary_vals = ", ".join(str(c.normalized_value) for c in top_candidates[:4])
            results.append(
                ExtractedMetricRecord(
                    cik=filing.cik,
                    ticker=filing.ticker,
                    accession_number=filing.accession_number,
                    form_type=filing.form_type,
                    metric_name=metric.name,
                    xbrl_concept=top_candidates[0].concept,
                    reported_unit=top_candidates[0].reported_unit,
                    currency=top_candidates[0].currency,
                    fiscal_period=top_candidates[0].fiscal_period,
                    fiscal_year=top_candidates[0].fiscal_year or filing.fiscal_year,
                    period_start=top_candidates[0].period_start,
                    period_end=top_candidates[0].period_end,
                    source_url=filing.filing_url,
                    evidence_snippet=(
                        f"Ambiguous candidates detected ({len(distinct_values)} distinct values: "
                        f"{summary_vals}); requires human review."
                    ),
                    evidence_location=top_candidates[0].evidence_location,
                    extraction_status="AMBIGUOUS",
                    review_status="REVIEW_REQUIRED",
                    validation_status="AMBIGUOUS",
                    candidates=deduped,
                )
            )
            continue

        winner = top_candidates[0]
        source_url = (
            filing.filing_url
            if "html" in winner.source
            else filing.companyfacts_url
        )
        results.append(
            ExtractedMetricRecord(
                cik=filing.cik,
                ticker=filing.ticker,
                accession_number=filing.accession_number,
                form_type=filing.form_type,
                metric_name=metric.name,
                xbrl_concept=winner.concept,
                raw_value=winner.raw_value,
                normalized_value=winner.normalized_value,
                reported_unit=winner.reported_unit,
                currency=winner.currency,
                scale_factor=winner.scale_factor,
                fiscal_period=winner.fiscal_period,
                fiscal_year=winner.fiscal_year or filing.fiscal_year,
                period_start=winner.period_start,
                period_end=winner.period_end,
                source_url=source_url,
                evidence_snippet=winner.evidence_snippet,
                evidence_location=winner.evidence_location,
                extraction_status="EXTRACTED",
                review_status="EXTRACTED",
                validation_status="PENDING",
                candidates=deduped,
            )
        )

    metric_by_name = {m.name: m for m in target_metrics}
    html_checked = parsed_html is not None
    for record in results:
        assessment = score_extracted_metric(
            record,
            metric_def=metric_by_name.get(record.metric_name),
            filing_reporting_period=filing.reporting_period,
            html_checked=html_checked,
            settings=confidence_settings,
        )
        record.confidence_score = assessment.score
        record.confidence_components = assessment.components_dict()
        record.confidence_reasons = assessment.reasons
        record.confidence_threshold = assessment.threshold
        record.scoring_version = assessment.scoring_version
        record.confidence_explanation = assessment.explanation
        record.review_status = assessment.decision

    if persist:
        init_db(db_path)
        with get_connection(db_path) as conn:
            filing_row = conn.execute(
                "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
                (filing.cik, filing.accession_number),
            ).fetchone()
            filing_id = int(filing_row["id"]) if filing_row else None
            save_extracted_metrics(
                records=[r.to_db_row(run_id=run_id) for r in results],
                cik=filing.cik,
                accession_number=filing.accession_number,
                db_path=db_path,
                conn=conn,
            )
            escalated_tasks = [
                {
                    "run_id": run_id,
                    "ticker": filing.ticker,
                    "metric_name": r.metric_name,
                    "reason": r.confidence_reasons[-1]
                    if r.confidence_reasons
                    else "Confidence score below approval threshold.",
                    "created_at": r.created_at,
                }
                for r in results
                if r.review_status == "REVIEW_REQUIRED"
            ]
            sync_review_tasks_for_filing(
                tasks=escalated_tasks,
                cik=filing.cik,
                accession_number=filing.accession_number,
                db_path=db_path,
                conn=conn,
            )
            extracted_count = sum(1 for r in results if r.extraction_status == "EXTRACTED")
            ambiguous_count = sum(1 for r in results if r.extraction_status == "AMBIGUOUS")
            missing_count = sum(1 for r in results if r.extraction_status == "MISSING")
            auto_approved_count = sum(1 for r in results if r.review_status == "AUTO_APPROVED")
            escalated_count = len(escalated_tasks)
            record_audit_event(
                event_type="METRICS_EXTRACTED",
                actor="extractor",
                run_id=run_id,
                cik=filing.cik,
                ticker=filing.ticker,
                company_name=filing.company_name,
                filing_id=filing_id,
                accession_number=filing.accession_number,
                decision="METRICS_EXTRACTED",
                explanation=(
                    f"Extracted {extracted_count}, ambiguous {ambiguous_count}, missing {missing_count}; "
                    f"{auto_approved_count} auto-approved, {escalated_count} escalated."
                ),
                payload={
                    "cik": filing.cik,
                    "ticker": filing.ticker,
                    "company_name": filing.company_name,
                    "filing_id": filing_id,
                    "accession_number": filing.accession_number,
                    "extracted": extracted_count,
                    "ambiguous": ambiguous_count,
                    "missing": missing_count,
                    "auto_approved": auto_approved_count,
                    "escalated_for_review": escalated_count,
                    "scoring_version": results[0].scoring_version if results else None,
                    "confidence_threshold": results[0].confidence_threshold if results else None,
                },
                conn=conn,
            )
            if escalated_tasks:
                record_audit_event(
                    event_type="HUMAN_REVIEW_ESCALATED",
                    actor="confidence_scorer",
                    run_id=run_id,
                    cik=filing.cik,
                    ticker=filing.ticker,
                    company_name=filing.company_name,
                    filing_id=filing_id,
                    accession_number=filing.accession_number,
                    decision="ESCALATED",
                    explanation=f"Escalated {len(escalated_tasks)} metric(s) below confidence/quality criteria.",
                    payload={
                        "cik": filing.cik,
                        "ticker": filing.ticker,
                        "company_name": filing.company_name,
                        "filing_id": filing_id,
                        "accession_number": filing.accession_number,
                        "escalated_metrics": [t["metric_name"] for t in escalated_tasks],
                    },
                    conn=conn,
                )

    if run_validations:
        run_financial_validations(
            results,
            cik=filing.cik,
            ticker=filing.ticker,
            accession_number=filing.accession_number,
            company_facts=company_facts,
            parsed_html=parsed_html,
            settings=validation_settings,
            persist=persist,
            run_id=run_id,
            db_path=db_path,
        )

    return results


def extract_10k_metrics_from_sec(
    ticker: str,
    client: SecEdgarClient | None = None,
    include_html: bool = True,
    force_refresh: bool = False,
    persist: bool = True,
    db_path: Path | str | None = None,
) -> list[ExtractedMetricRecord]:
    """Fetch a company's latest 10-K metadata, Company Facts, and HTML, then extract 8 metrics."""
    sec_client = client or SecEdgarClient()
    bundle = sec_client.fetch_latest_10k_bundle(
        ticker=ticker,
        persist=persist,
        force_refresh=force_refresh,
        db_path=db_path,
    )
    html_text: str | None = None
    if include_html:
        html_text, _, _ = sec_client.get_filing_html(
            filing_url=bundle.latest_10k.filing_url,
            cik=bundle.latest_10k.cik,
            accession_number=bundle.latest_10k.accession_number,
            primary_document=bundle.latest_10k.primary_document,
            force_refresh=force_refresh,
        )

    return extract_metrics_for_filing(
        filing=bundle.latest_10k,
        company_facts=bundle.company_facts.facts,
        html_text=html_text,
        persist=persist,
        db_path=db_path,
    )
