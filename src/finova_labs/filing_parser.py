"""SEC 10-K HTML and Inline XBRL financial table parsing utilities."""

from __future__ import annotations

import re
import warnings
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from pydantic import BaseModel, Field

from finova_labs.logging_config import get_logger
from finova_labs.normalization import (
    apply_scale,
    normalize_unit,
    parse_numeric_text,
    scale_power_from_text,
)

logger = get_logger("filing_parser")
_WHITESPACE_RE = re.compile(r"\s+")


class XbrlContext(BaseModel):
    """Parsed Inline XBRL context period and dimensionality."""

    context_id: str
    start_date: str | None = None
    end_date: str | None = None
    instant: str | None = None
    has_dimensions: bool = False
    dimensions: dict[str, str] = Field(default_factory=dict)


class HtmlFactEvidence(BaseModel):
    """Single numeric fact extracted from a 10-K HTML / Inline XBRL document."""

    concept: str
    namespace: str | None = None
    raw_value: str
    normalized_value: Decimal
    scale_power: int = 0
    scale_factor: Decimal = Decimal(1)
    reported_unit: str = "USD"
    currency: str = "USD"
    period_start: str | None = None
    period_end: str | None = None
    has_dimensions: bool = False
    dimensions: dict[str, str] = Field(default_factory=dict)
    context_ref: str | None = None
    row_label: str | None = None
    evidence_snippet: str
    evidence_location: str


class ParsedFilingHtml(BaseModel):
    """Structured Inline XBRL facts and table rows extracted from 10-K HTML."""

    facts: list[HtmlFactEvidence]
    facts_by_concept: dict[str, list[HtmlFactEvidence]]
    table_count: int = 0


def _clean_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _local_name(tag_name: str | None) -> str:
    if not tag_name:
        return ""
    return tag_name.split(":")[-1].lower()


def _parse_contexts(soup: BeautifulSoup) -> dict[str, XbrlContext]:
    contexts: dict[str, XbrlContext] = {}
    for elem in soup.find_all(lambda t: isinstance(t, Tag) and _local_name(t.name) == "context"):
        ctx_id = elem.get("id")
        if not ctx_id:
            continue

        start_el = elem.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "startdate")
        end_el = elem.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "enddate")
        inst_el = elem.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "instant")
        dim_el = elem.find(
            lambda t: isinstance(t, Tag)
            and _local_name(t.name) in {"segment", "explicitmember", "typedmember"}
        )
        dimensions: dict[str, str] = {}
        for mem_el in elem.find_all(
            lambda t: isinstance(t, Tag)
            and _local_name(t.name) in {"explicitmember", "typedmember"}
        ):
            dim_attr = str(mem_el.get("dimension") or "").strip()
            dim_local = dim_attr.split(":")[-1] if ":" in dim_attr else dim_attr
            mem_text = _clean_text(mem_el.get_text())
            mem_local = mem_text.split(":")[-1] if ":" in mem_text else mem_text
            if dim_local and mem_local:
                dimensions[dim_local] = mem_local

        contexts[ctx_id] = XbrlContext(
            context_id=ctx_id,
            start_date=_clean_text(start_el.get_text()) if start_el else None,
            end_date=_clean_text(end_el.get_text()) if end_el else None,
            instant=_clean_text(inst_el.get_text()) if inst_el else None,
            has_dimensions=bool(dimensions) or (dim_el is not None),
            dimensions=dimensions,
        )
    return contexts


def _parse_units(soup: BeautifulSoup) -> dict[str, str]:
    units: dict[str, str] = {}
    for elem in soup.find_all(lambda t: isinstance(t, Tag) and _local_name(t.name) == "unit"):
        unit_id = elem.get("id")
        if not unit_id:
            continue

        divide_el = elem.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "divide")
        if divide_el is not None:
            num_el = divide_el.find(
                lambda t: isinstance(t, Tag) and _local_name(t.name) == "unitnumerator"
            )
            den_el = divide_el.find(
                lambda t: isinstance(t, Tag) and _local_name(t.name) == "unitdenominator"
            )
            num_m = num_el.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "measure") if num_el else None
            den_m = den_el.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "measure") if den_el else None
            if num_m and den_m:
                num_txt = _clean_text(num_m.get_text()).split(":")[-1].upper()
                den_txt = _clean_text(den_m.get_text()).split(":")[-1].lower()
                units[unit_id] = f"{num_txt}/{den_txt}"
                continue

        measure_el = elem.find(lambda t: isinstance(t, Tag) and _local_name(t.name) == "measure")
        if measure_el:
            raw_measure = _clean_text(measure_el.get_text())
            units[unit_id] = raw_measure.split(":")[-1].upper()
    return units


def parse_filing_html(html_text: str) -> ParsedFilingHtml:
    """Parse Inline XBRL facts and HTML table locations from a SEC 10-K document."""
    if not html_text or not html_text.strip():
        return ParsedFilingHtml(facts=[], facts_by_concept={}, table_count=0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html_text, "lxml")

    contexts = _parse_contexts(soup)
    units = _parse_units(soup)

    tables = soup.find_all("table")
    table_index_map: dict[int, int] = {}
    row_index_map: dict[int, tuple[int, int]] = {}
    for t_idx, tbl in enumerate(tables, start=1):
        table_index_map[id(tbl)] = t_idx
        for r_idx, tr_el in enumerate(tbl.find_all("tr"), start=1):
            row_index_map[id(tr_el)] = (t_idx, r_idx)

    facts: list[HtmlFactEvidence] = []
    by_concept: dict[str, list[HtmlFactEvidence]] = {}

    for elem in soup.find_all(lambda t: isinstance(t, Tag) and _local_name(t.name) == "nonfraction"):
        full_name = str(elem.get("name", "")).strip()
        if not full_name:
            continue
        if ":" in full_name:
            namespace, concept = full_name.split(":", 1)
        else:
            namespace, concept = None, full_name

        raw_text = _clean_text(elem.get_text())
        sign_attr = elem.get("sign")
        parsed = parse_numeric_text(raw_text, sign_attr=str(sign_attr) if sign_attr else None)
        if parsed is None:
            continue

        scale_raw = str(elem.get("scale", "0")).strip()
        try:
            scale_power = int(scale_raw)
        except ValueError:
            scale_power = 0

        normalized, scale_factor = apply_scale(parsed, scale_power=scale_power)

        ctx_ref = str(elem.get("contextref") or elem.get("contextRef") or "").strip() or None
        ctx = contexts.get(ctx_ref) if ctx_ref else None
        period_start = ctx.start_date if ctx else None
        period_end = (ctx.instant or ctx.end_date) if ctx else None
        has_dimensions = ctx.has_dimensions if ctx else False
        dimensions = dict(ctx.dimensions) if ctx else {}

        unit_ref = str(elem.get("unitref") or elem.get("unitRef") or "").strip() or None
        raw_unit = units.get(unit_ref, unit_ref or "USD") if unit_ref else "USD"
        reported_unit, currency = normalize_unit(raw_unit)

        tr = elem.find_parent("tr")
        table = elem.find_parent("table")
        row_label: str | None = None
        if tr is not None:
            cells = [_clean_text(td.get_text()) for td in tr.find_all(["td", "th"])]
            non_empty = [c for c in cells if c]
            if non_empty:
                row_label = non_empty[0][:120]
            snippet_raw = " | ".join(non_empty[:6])
        else:
            parent_block = elem.parent
            snippet_raw = _clean_text(parent_block.get_text()) if parent_block else raw_text

        snippet = snippet_raw[:240] + ("…" if len(snippet_raw) > 240 else "")

        if tr is not None and id(tr) in row_index_map:
            t_idx, row_idx = row_index_map[id(tr)]
            location = f"10-K HTML Table #{t_idx}, Row #{row_idx}"
        elif table is not None and id(table) in table_index_map:
            location = f"10-K HTML Table #{table_index_map[id(table)]}"
        else:
            location = f"10-K HTML Inline XBRL (context={ctx_ref or 'unknown'})"

        fact = HtmlFactEvidence(
            concept=concept,
            namespace=namespace,
            raw_value=f"-{raw_text}" if (sign_attr == "-" and not raw_text.startswith("-")) else raw_text,
            normalized_value=normalized,
            scale_power=scale_power,
            scale_factor=scale_factor,
            reported_unit=reported_unit,
            currency=currency,
            period_start=period_start,
            period_end=period_end,
            has_dimensions=has_dimensions,
            dimensions=dimensions,
            context_ref=ctx_ref,
            row_label=row_label,
            evidence_snippet=snippet,
            evidence_location=location,
        )
        facts.append(fact)
        by_concept.setdefault(concept, []).append(fact)

    logger.info(
        "Parsed 10-K HTML: %s tables, %s Inline XBRL numeric facts",
        len(tables),
        len(facts),
    )
    return ParsedFilingHtml(
        facts=facts,
        facts_by_concept=by_concept,
        table_count=len(tables),
    )


def find_table_row_by_label(
    html_text: str,
    label_candidates: tuple[str, ...],
) -> dict[str, Any] | None:
    """Fallback HTML table scanner returning first matching row label, values, and scale hint."""
    if not html_text:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html_text, "lxml")

    lowered = tuple(lbl.lower() for lbl in label_candidates)
    for t_idx, table in enumerate(soup.find_all("table"), start=1):
        table_text = _clean_text(table.get_text(" ", strip=True))
        scale_power = scale_power_from_text(table_text[:400])
        for r_idx, tr in enumerate(table.find_all("tr"), start=1):
            cells = [_clean_text(c.get_text()) for c in tr.find_all(["td", "th"])]
            non_empty = [c for c in cells if c]
            if not non_empty:
                continue
            first_cell = non_empty[0].lower()
            if any(lbl in first_cell for lbl in lowered):
                return {
                    "row_label": non_empty[0],
                    "cells": non_empty,
                    "scale_power": scale_power,
                    "evidence_snippet": " | ".join(non_empty[:6])[:240],
                    "evidence_location": f"10-K HTML Table #{t_idx}, Row #{r_idx}",
                }
    return None
