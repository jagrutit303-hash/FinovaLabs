"""Decimal normalization of reporting periods, units, scale factors, and signs."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

_QUARTERLY_FRAME_RE = re.compile(r"Q[1-4]", re.IGNORECASE)
_IN_SCALE_RE = re.compile(r"\bin\s+(thousands|millions|billions)\b", re.IGNORECASE)


class PeriodClassification(BaseModel):
    """Normalized classification of a financial reporting period."""

    period_kind: Literal["ANNUAL", "QUARTERLY", "YTD", "INSTANT", "OTHER", "UNKNOWN"]
    is_annual: bool
    duration_days: int | None = None
    fiscal_period: str | None = None


def parse_numeric_text(
    raw_value: str | int | float | Decimal,
    sign_attr: str | None = None,
) -> Decimal | None:
    """Parse raw filing or XBRL numeric values into Decimal, handling negatives."""
    if isinstance(raw_value, Decimal):
        val = raw_value
    elif isinstance(raw_value, bool):
        return None
    elif isinstance(raw_value, int):
        val = Decimal(raw_value)
    elif isinstance(raw_value, float):
        val = Decimal(str(raw_value))
    else:
        text = str(raw_value).strip()
        if not text or text in {"—", "–", "-", "N/A", "n/a", "nil"}:
            return None

        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1].strip()

        text = (
            text.replace("$", "")
            .replace(",", "")
            .replace("\u00a0", "")
            .replace("−", "-")
            .strip()
        )
        if text.startswith("-"):
            negative = not negative
            text = text[1:].strip()

        try:
            val = Decimal(text)
        except InvalidOperation:
            return None

        if negative:
            val = -abs(val)

    if sign_attr and sign_attr.strip() == "-":
        val = -abs(val)

    return val


def scale_power_from_text(scale_hint: str | None) -> int:
    """Infer base-10 exponent from table unit phrases like 'in millions'."""
    if not scale_hint:
        return 0
    match = _IN_SCALE_RE.search(scale_hint)
    if not match:
        return 0
    word = match.group(1).lower()
    return {"thousands": 3, "millions": 6, "billions": 9}.get(word, 0)


def apply_scale(value: Decimal, scale_power: int = 0) -> tuple[Decimal, Decimal]:
    """Scale a Decimal by 10**scale_power and return ``(scaled_value, factor)``."""
    factor = Decimal(10) ** int(scale_power)
    scaled = value * factor
    return scaled, factor


def normalize_unit(raw_unit: str | None, fallback_unit: str = "USD") -> tuple[str, str]:
    """Normalize SEC unit identifiers into ``(reported_unit, currency)``."""
    if not raw_unit or not raw_unit.strip():
        unit = fallback_unit
    else:
        cleaned = raw_unit.strip()
        lower = cleaned.lower()
        if lower in {"usd", "iso4217:usd"}:
            unit = "USD"
        elif "usd" in lower and "share" in lower:
            unit = "USD/shares"
        else:
            unit = cleaned

    currency = "USD" if "USD" in unit.upper() else unit.split("/")[0].upper()
    return unit, currency


def _parse_iso_date(date_str: str | None) -> date | None:
    if not date_str or len(date_str.strip()) < 10:
        return None
    try:
        return date.fromisoformat(date_str.strip()[:10])
    except ValueError:
        return None


def classify_period(
    start_date: str | None,
    end_date: str | None,
    fp: str | None = None,
    frame: str | None = None,
    expected_kind: Literal["duration", "instant"] = "duration",
) -> PeriodClassification:
    """Distinguish annual 10-K periods from quarterly, YTD, and instant snapshots."""
    end_dt = _parse_iso_date(end_date)
    start_dt = _parse_iso_date(start_date)
    fp_norm = fp.strip().upper() if fp else None
    frame_norm = frame.strip().upper() if frame else None

    if start_dt is None and end_dt is not None:
        is_annual_instant = expected_kind == "instant" and (
            fp_norm in {None, "FY"}
            and (frame_norm is None or frame_norm.endswith("I"))
        )
        return PeriodClassification(
            period_kind="INSTANT",
            is_annual=is_annual_instant,
            duration_days=None,
            fiscal_period=fp_norm or "FY",
        )

    if start_dt is None or end_dt is None:
        return PeriodClassification(
            period_kind="UNKNOWN",
            is_annual=False,
            duration_days=None,
            fiscal_period=fp_norm,
        )

    days = (end_dt - start_dt).days
    if frame_norm and _QUARTERLY_FRAME_RE.search(frame_norm) and not frame_norm.endswith("I"):
        return PeriodClassification(
            period_kind="QUARTERLY" if days <= 115 else "YTD",
            is_annual=False,
            duration_days=days,
            fiscal_period=fp_norm,
        )

    if 330 <= days <= 385:
        return PeriodClassification(
            period_kind="ANNUAL",
            is_annual=True,
            duration_days=days,
            fiscal_period=fp_norm or "FY",
        )
    if 70 <= days <= 115:
        return PeriodClassification(
            period_kind="QUARTERLY",
            is_annual=False,
            duration_days=days,
            fiscal_period=fp_norm,
        )
    if 150 <= days <= 300:
        return PeriodClassification(
            period_kind="YTD",
            is_annual=False,
            duration_days=days,
            fiscal_period=fp_norm,
        )
    return PeriodClassification(
        period_kind="OTHER",
        is_annual=False,
        duration_days=days,
        fiscal_period=fp_norm,
    )
