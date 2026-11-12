"""Tests for Decimal parsing, unit/scale normalization, and annual vs quarterly period checks."""

from __future__ import annotations

from decimal import Decimal

from finova_labs.normalization import (
    apply_scale,
    classify_period,
    normalize_unit,
    parse_numeric_text,
    scale_power_from_text,
)


def test_parse_numeric_text_handles_negatives_and_formatting() -> None:
    """Accounting parentheses, currency symbols, and sign attributes parse to Decimal."""
    assert parse_numeric_text("(1,234.56)") == Decimal("-1234.56")
    assert parse_numeric_text("$478,834") == Decimal("478834")
    assert parse_numeric_text("1,500", sign_attr="-") == Decimal("-1500")
    assert parse_numeric_text("—") is None


def test_decimal_scaling_and_unit_normalization() -> None:
    """Decimal scaling avoids float precision issues and normalizes units/currency."""
    scaled, factor = apply_scale(Decimal("478834"), scale_power=6)
    assert scaled == Decimal("478834000000")
    assert factor == 1_000_000
    assert scale_power_from_text("Consolidated Balance Sheets (in millions)") == 6
    assert scale_power_from_text("Amounts in thousands") == 3

    assert normalize_unit("iso4217:USD") == ("USD", "USD")
    assert normalize_unit("USD/shares") == ("USD/shares", "USD")


def test_classify_period_distinguishes_annual_quarterly_ytd_and_instant() -> None:
    """Annual durations (~365d) are separated from 3-month, 9-month YTD, and instant."""
    annual = classify_period("2025-09-28", "2026-09-26", fp="FY", frame="CY2026", expected_kind="duration")
    assert annual.period_kind == "ANNUAL"
    assert annual.is_annual is True

    quarterly = classify_period("2026-06-28", "2026-09-26", fp="Q4", frame="CY2026Q3", expected_kind="duration")
    assert quarterly.period_kind == "QUARTERLY"
    assert quarterly.is_annual is False

    ytd = classify_period("2025-09-28", "2026-06-27", fp="Q3", expected_kind="duration")
    assert ytd.period_kind == "YTD"
    assert ytd.is_annual is False

    instant = classify_period(None, "2026-09-26", fp="FY", expected_kind="instant")
    assert instant.period_kind == "INSTANT"
    assert instant.is_annual is True
