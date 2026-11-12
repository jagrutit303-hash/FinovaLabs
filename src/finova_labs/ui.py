"""Shared enterprise fintech UI theme and reusable components for FinovaLabs."""

from __future__ import annotations

import base64
from html import escape
import inspect
from typing import Any, Callable, Sequence, TypeVar

import streamlit as st

from finova_labs import PRODUCT_NAME, PRODUCT_TAGLINE
from finova_labs.exceptions import FinovaError
from finova_labs.logging_config import get_logger

logger = get_logger("ui")
T = TypeVar("T")

_LOGO_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" fill="none">
  <rect width="40" height="40" rx="10" fill="#1D4ED8"/>
  <path d="M10 29V11H28V15.5H15.2V18.6H25.2V22.9H15.2V29H10Z" fill="#FFFFFF"/>
  <circle cx="29" cy="27" r="3.5" fill="#60A5FA"/>
</svg>
""".strip()

_FAVICON_URI = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_LOGO_SVG.encode("utf-8")).decode("ascii")
)

_TONE_CLASSES = {"success", "warning", "danger", "info", "neutral"}

_ENTERPRISE_CSS = """
<style>
  :root {
    --fl-navy-950: #071324;
    --fl-navy-900: #0B1E36;
    --fl-navy-800: #122B4D;
    --fl-blue-700: #1D4ED8;
    --fl-blue-600: #2563EB;
    --fl-blue-500: #3B82F6;
    --fl-blue-300: #93C5FD;
    --fl-blue-50: #EFF6FF;
    --fl-slate-900: #0F172A;
    --fl-slate-700: #334155;
    --fl-slate-600: #475569;
    --fl-slate-500: #475569;
    --fl-border: #E2E8F0;
    --fl-surface: #FFFFFF;
    --fl-canvas: #F8FAFC;
  }

  .stApp {
    background-color: var(--fl-canvas);
    color: var(--fl-slate-900);
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }

  .block-container {
    padding-top: 1.15rem;
    padding-bottom: 2rem;
    max-width: 1280px;
  }

  /* Deep navy enterprise sidebar */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--fl-navy-950) 0%, var(--fl-navy-900) 55%, var(--fl-navy-800) 100%);
    border-right: 1px solid rgba(147, 197, 253, 0.16);
    color: #E2E8F0;
  }

  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label {
    color: #E2E8F0;
  }

  [data-testid="stSidebarNav"] {
    padding-top: 0.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid rgba(147, 197, 253, 0.14);
    margin-bottom: 0.9rem;
  }

  [data-testid="stSidebarNav"] a {
    border-radius: 8px;
    margin: 0.18rem 0.5rem;
    padding: 0.48rem 0.75rem;
    transition: background-color 0.15s ease, border-color 0.15s ease;
    border-left: 3px solid transparent;
  }

  [data-testid="stSidebarNav"] a:hover {
    background-color: rgba(59, 130, 246, 0.16);
  }

  [data-testid="stSidebarNav"] a[aria-current="page"] {
    background-color: rgba(37, 99, 235, 0.28);
    border-left: 3px solid #60A5FA;
    font-weight: 600;
  }

  [data-testid="stSidebarNav"] span {
    color: #F8FAFC !important;
    font-size: 0.92rem;
  }

  [data-testid="stSidebarCollapseButton"] svg {
    fill: #CBD5E1;
  }

  /* Primary buttons styled for enterprise blue */
  .stButton > button {
    border-radius: 8px;
    border: 1px solid #CBD5E1;
    background-color: #FFFFFF;
    color: var(--fl-navy-900);
    font-weight: 600;
    font-size: 0.88rem;
    padding: 0.45rem 0.95rem;
    transition: all 0.15s ease;
  }

  .stButton > button:hover {
    border-color: var(--fl-blue-600);
    color: var(--fl-blue-700);
    background-color: var(--fl-blue-50);
  }

  .stButton > button[kind="primary"] {
    background-color: var(--fl-blue-700);
    border-color: var(--fl-blue-700);
    color: #FFFFFF;
  }

  .stButton > button[kind="primary"]:hover {
    background-color: #1E40AF;
    border-color: #1E40AF;
    color: #FFFFFF;
  }

  .fl-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 0.85rem;
    margin: 0.25rem 0 0.85rem 0;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(147, 197, 253, 0.18);
    border-radius: 12px;
  }

  .fl-sidebar-brand-title {
    font-size: 1.08rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: #FFFFFF !important;
    line-height: 1.2;
  }

  .fl-sidebar-brand-tag {
    font-size: 0.74rem;
    color: #93C5FD !important;
    line-height: 1.3;
    margin-top: 0.15rem;
  }

  .fl-sidebar-meta {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(191, 219, 254, 0.22);
    border-radius: 10px;
    padding: 0.72rem 0.85rem;
    margin-top: 0.6rem;
    font-size: 0.82rem;
  }

  .fl-sidebar-meta-label {
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.75rem;
    color: #BFDBFE !important;
    font-weight: 600;
    margin-bottom: 0.28rem;
  }

  .fl-sidebar-meta-value {
    color: #F8FAFC !important;
    font-weight: 500;
    line-height: 1.45;
  }

  /* Compact enterprise compliance header */
  .fl-header {
    background: linear-gradient(135deg, #0A192F 0%, #102A4C 68%, #163B6B 100%);
    border: 1px solid #1E3A5F;
    border-radius: 12px;
    padding: 1.05rem 1.35rem;
    margin-bottom: 0.9rem;
    color: #FFFFFF;
    box-shadow: 0 6px 18px rgba(10, 25, 47, 0.07);
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 0.85rem;
  }

  .fl-header-eyebrow {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #BFDBFE;
    margin-bottom: 0.2rem;
  }

  .fl-header-title {
    font-size: 1.48rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #FFFFFF;
    margin: 0;
    line-height: 1.2;
  }

  .fl-header-subtitle {
    font-size: 0.92rem;
    color: #E2E8F0;
    margin: 0.3rem 0 0 0;
    max-width: 78ch;
    line-height: 1.45;
  }

  /* 7-stage compliance workflow progress indicator */
  .fl-stepper {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 0.42rem;
    margin-bottom: 0.9rem;
  }

  .fl-step {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-radius: 9px;
    padding: 0.46rem 0.56rem;
    font-size: 0.74rem;
    color: var(--fl-slate-600);
    display: flex;
    flex-direction: column;
    gap: 0.14rem;
    line-height: 1.25;
  }

  .fl-step-active {
    background: #EFF6FF;
    border-color: #2563EB;
    color: #1E3A8A;
    font-weight: 600;
    box-shadow: 0 2px 6px rgba(37, 99, 235, 0.08);
  }

  .fl-step-done {
    background: #ECFDF5;
    border-color: #6EE7B7;
    color: #065F46;
  }

  .fl-step-alert {
    background: #FFFBEB;
    border-color: #FCD34D;
    color: #92400E;
  }

  .fl-step-num {
    font-size: 0.69rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.92;
    font-weight: 700;
  }

  /* Beginner welcome, interactive tour & next-action callouts */
  .fl-welcome-card {
    background: linear-gradient(135deg, #F8FBFF 0%, #EFF6FF 100%);
    border: 1px solid #BFDBFE;
    border-left: 4px solid #1D4ED8;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.85rem;
    color: var(--fl-slate-900);
  }

  .fl-welcome-title {
    font-size: 1.04rem;
    font-weight: 700;
    color: var(--fl-navy-900);
    margin: 0 0 0.35rem 0;
  }

  .fl-welcome-body {
    font-size: 0.88rem;
    color: var(--fl-slate-700);
    line-height: 1.5;
    margin: 0;
  }

  .fl-tour-card {
    background: #0A192F;
    border: 1px solid #1D4ED8;
    border-radius: 12px;
    padding: 0.95rem 1.2rem;
    margin-bottom: 0.85rem;
    color: #F8FAFC;
  }

  .fl-tour-eyebrow {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #93C5FD;
    margin-bottom: 0.25rem;
  }

  .fl-tour-title {
    font-size: 1.02rem;
    font-weight: 700;
    color: #FFFFFF;
    margin: 0 0 0.3rem 0;
  }

  .fl-tour-body {
    font-size: 0.87rem;
    color: #E2E8F0;
    line-height: 1.5;
    margin: 0;
  }

  .fl-next-box {
    background: #F8FAFC;
    border: 1px solid var(--fl-border);
    border-left: 4px solid #0284C7;
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.85rem;
    font-size: 0.86rem;
    color: var(--fl-slate-800);
    line-height: 1.48;
  }

  .fl-tip {
    text-decoration: none;
    border-bottom: 1px dotted #64748B;
    cursor: help;
  }

  .fl-sidebar-help-list {
    margin: 0.25rem 0 0.55rem 1.05rem;
    padding: 0;
    font-size: 0.8rem;
    color: #E2E8F0 !important;
    line-height: 1.48;
  }

  .fl-sidebar-help-list li {
    margin-bottom: 0.28rem;
  }

  /* Responsive KPI / Summary Cards */
  .fl-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 0.85rem;
    margin-bottom: 1rem;
  }

  .fl-card {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-radius: 12px;
    padding: 1.15rem 1.25rem;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  .fl-card:hover {
    border-color: #BFDBFE;
    box-shadow: 0 4px 12px rgba(29, 78, 216, 0.06);
  }

  .fl-kpi-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fl-slate-500);
    margin-bottom: 0.42rem;
  }

  .fl-kpi-value {
    font-size: 1.48rem;
    font-weight: 700;
    color: var(--fl-navy-900);
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
  }

  .fl-kpi-detail {
    font-size: 0.83rem;
    color: var(--fl-slate-500);
    margin-top: 0.38rem;
    line-height: 1.4;
  }

  .fl-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.6rem;
  }

  .fl-card-title {
    font-size: 1.02rem;
    font-weight: 600;
    color: var(--fl-navy-900);
    margin: 0;
  }

  .fl-card-body {
    font-size: 0.92rem;
    color: var(--fl-slate-700);
    line-height: 1.55;
    margin: 0;
  }

  .fl-section-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--fl-navy-900);
    letter-spacing: -0.01em;
    margin: 1.25rem 0 0.7rem 0;
  }

  /* Realistic Empty State */
  .fl-empty {
    background: var(--fl-surface);
    border: 1px dashed #CBD5E1;
    border-radius: 12px;
    padding: 2rem 1.5rem;
    text-align: center;
    margin-bottom: 1.25rem;
  }

  .fl-empty-badge {
    display: inline-block;
    padding: 0.25rem 0.7rem;
    border-radius: 999px;
    background: var(--fl-blue-50);
    color: var(--fl-blue-700);
    border: 1px solid #BFDBFE;
    font-size: 0.74rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.7rem;
  }

  .fl-empty-title {
    font-size: 1.06rem;
    font-weight: 700;
    color: var(--fl-navy-900);
    margin: 0 0 0.4rem 0;
  }

  .fl-empty-desc {
    font-size: 0.9rem;
    color: var(--fl-slate-500);
    max-width: 58ch;
    margin: 0 auto;
    line-height: 1.55;
  }

  .fl-empty-next {
    margin-top: 0.85rem;
    font-size: 0.83rem;
    color: var(--fl-slate-700);
    font-weight: 500;
  }

  /* Clear Error Banner */
  .fl-error-box {
    background: #FEF2F2;
    border: 1px solid #FECACA;
    border-left: 4px solid #DC2626;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 1rem;
    color: #7F1D1D;
  }

  .fl-error-title {
    font-weight: 700;
    font-size: 0.96rem;
    margin-bottom: 0.25rem;
  }

  .fl-error-hint {
    margin-top: 0.35rem;
    font-size: 0.85rem;
    color: #991B1B;
  }

  /* Semantic Status Badges */
  .fl-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.24rem 0.68rem;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
    line-height: 1.2;
    white-space: nowrap;
    border: 1px solid transparent;
  }

  .fl-badge-dot {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: currentColor;
  }

  .fl-badge-success {
    color: #047857;
    background: #ECFDF5;
    border-color: #A7F3D0;
  }

  .fl-badge-warning {
    color: #B45309;
    background: #FFFBEB;
    border-color: #FDE68A;
  }

  .fl-badge-danger {
    color: #B91C1C;
    background: #FEF2F2;
    border-color: #FECACA;
  }

  .fl-badge-info {
    color: #1D4ED8;
    background: #EFF6FF;
    border-color: #BFDBFE;
  }

  .fl-badge-neutral {
    color: #475569;
    background: #F1F5F9;
    border-color: #CBD5E1;
  }

  /* Modern Responsive Table */
  .fl-table-wrap {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-radius: 12px;
    overflow-x: auto;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    margin-bottom: 1.25rem;
  }

  .fl-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.89rem;
    text-align: left;
  }

  .fl-table thead th {
    background: #F1F5F9;
    color: var(--fl-navy-900);
    font-weight: 600;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.78rem 1rem;
    border-bottom: 1px solid var(--fl-border);
    white-space: nowrap;
  }

  .fl-table tbody td {
    padding: 0.72rem 0.9rem;
    border-bottom: 1px solid #F1F5F9;
    color: var(--fl-slate-700);
    vertical-align: middle;
    font-variant-numeric: tabular-nums;
  }

  .fl-table tbody td.fl-num,
  .fl-table thead th.fl-num {
    text-align: right;
  }

  .fl-evidence-box {
    background: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-left: 4px solid #1D4ED8;
    border-radius: 8px;
    padding: 0.75rem 0.9rem;
    font-size: 0.87rem;
    color: var(--fl-slate-900);
    line-height: 1.5;
    margin-top: 0.4rem;
  }

  .fl-action-banner {
    background: #FFFFFF;
    border: 1px solid #BFDBFE;
    border-left: 4px solid #1D4ED8;
    border-radius: 10px;
    padding: 0.85rem 1.05rem;
    margin-bottom: 0.85rem;
  }

  .fl-action-banner-warning {
    border-color: #FCD34D;
    border-left-color: #D97706;
    background: #FFFDF5;
  }

  .fl-action-banner-success {
    border-color: #A7F3D0;
    border-left-color: #059669;
    background: #F6FEF9;
  }

  .fl-table tbody tr:last-child td {
    border-bottom: none;
  }

  .fl-table tbody tr:hover {
    background: #F8FAFC;
  }

  .fl-footer {
    margin-top: 1.5rem;
    padding-top: 0.85rem;
    border-top: 1px solid var(--fl-border);
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: 0.8rem;
    color: var(--fl-slate-600);
  }

  @media (max-width: 1180px) {
    .fl-stepper {
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    }
  }

  @media (max-width: 768px) {
    .block-container {
      padding-top: 0.9rem;
      padding-left: 0.9rem;
      padding-right: 0.9rem;
    }
    .fl-stepper {
      grid-template-columns: 1fr;
    }
    .fl-header {
      padding: 0.95rem 1rem;
    }
    .fl-header-title {
      font-size: 1.32rem;
    }
  }
</style>
"""


def configure_page(section_title: str | None = None) -> None:
    """Configure Streamlit page title, favicon, and wide responsive layout."""
    title = (
        f"{section_title} | {PRODUCT_NAME}"
        if section_title
        else f"{PRODUCT_NAME} | {PRODUCT_TAGLINE}"
    )
    st.set_page_config(
        page_title=title,
        page_icon=_FAVICON_URI,
        layout="wide",
        initial_sidebar_state="expanded",
    )


_STATUS_LABELS: dict[str, str] = {
    "AUTO_APPROVED": "Auto-Approved",
    "APPROVED": "Approved",
    "CORRECTED": "Corrected",
    "EDITED": "Corrected",
    "REVIEW_REQUIRED": "Needs Review",
    "PAUSED_FOR_REVIEW": "Paused for Review",
    "COMPLETED_WITH_REJECTIONS": "Completed (With Rejections)",
    "COMPLETED": "Completed",
    "INTERRUPTED": "Interrupted",
    "RUNNING": "Running",
    "PENDING": "Pending",
    "FAILED": "Failed",
    "OPEN": "Pending",
    "REJECTED": "Rejected",
    "EXTRACTED": "Extracted",
    "AMBIGUOUS": "Ambiguous",
    "MISSING": "Missing",
    "RETRIEVED": "Retrieved",
    "EXACT_MATCH": "Exact Match",
    "MATCH_FOUND": "Matched",
    "MISMATCH": "Mismatch",
    "UNMATCHED_RECORD": "Unmatched",
    "PERIOD_MISMATCH": "Period Mismatch",
    "UNIT_MISMATCH": "Unit Mismatch",
    "UNAVAILABLE_REFERENCE": "No SEC Reference",
    "NOT_APPLICABLE": "Not Applicable",
    "NOT_REQUIRED": "Not Required",
}


def humanize_status(status: str | None) -> str:
    """Convert internal snake-case/enum tokens into scannable compliance labels."""
    if not status:
        return "—"
    cleaned = str(status).strip()
    return _STATUS_LABELS.get(cleaned.upper(), cleaned.replace("_", " ").title())


def status_badge(label: str, tone: str = "info") -> str:
    """Return an HTML status pill badge with semantic color coding."""
    safe_tone = tone if tone in _TONE_CLASSES else "neutral"
    return (
        f'<span class="fl-badge fl-badge-{safe_tone}">'
        f'<span class="fl-badge-dot"></span>{escape(label)}</span>'
    )


TOOLTIP_CONFIDENCE = (
    "Confidence Score (0%-100%): 5-factor weighted rating across Label/Concept Match (25%), "
    "Reporting Period Match (25%), Unit & Scale Correctness (20%), Evidence Quality (20%), "
    "and Independent-Path Agreement (10%). Metrics below 90% escalate automatically to Human Review."
)
TOOLTIP_EVIDENCE = (
    "Evidence: Verbatim text snippet, table/section location in the Form 10-K HTML, "
    "matched us-gaap XBRL concept, and official SEC EDGAR source URL."
)
TOOLTIP_PERIOD = (
    "Reporting Period: Annual Form 10-K duration (FY start -> end date) or balance-sheet instant date. "
    "Quarterly and mismatched dates are rejected before comparison."
)
TOOLTIP_UNIT = (
    "Units & Scale: Normalized currency/share unit (USD or USD/shares) plus reported table multiplier "
    "(1x, 1,000x, 1,000,000x) detected from Inline XBRL scale attributes and statement headers."
)
TOOLTIP_VALIDATION = (
    "Validation Status: Deterministic accounting check result (Pass, Warning, Fail, or Not Applicable) "
    "covering Assets = Liabilities + Equity, Segment Revenue reconciliation, and ±30% YoY change alerts. "
    "Any Fail pauses the workflow for Human Review even at 100% confidence."
)
TOOLTIP_CHECKPOINT = (
    "Workflow Checkpoint: Durable SQLite state saved after retrieval, extraction, scoring/validation, "
    "and human review so restarts resume safely without duplicating completed stages."
)

FIELD_TOOLTIPS: dict[str, str] = {
    "Confidence": TOOLTIP_CONFIDENCE,
    "Confidence Score": TOOLTIP_CONFIDENCE,
    "Evidence": TOOLTIP_EVIDENCE,
    "Citation": TOOLTIP_EVIDENCE,
    "Period": TOOLTIP_PERIOD,
    "Reporting Period": TOOLTIP_PERIOD,
    "Unit": TOOLTIP_UNIT,
    "Unit & Scale": TOOLTIP_UNIT,
    "Validation": TOOLTIP_VALIDATION,
    "Validation Status": TOOLTIP_VALIDATION,
    "Rule": TOOLTIP_VALIDATION,
    "Last Checkpoint": TOOLTIP_CHECKPOINT,
    "Stage": TOOLTIP_CHECKPOINT,
}

_TOUR_SCREENS: tuple[dict[str, str], ...] = (
    {
        "title": "Overview",
        "url_path": "overview",
        "purpose": (
            "Your command center showing live SQLite counts for retrieved companies/filings, "
            "auto-approved metrics, open human escalations, SEC benchmark accuracy, and resumable checkpoints."
        ),
        "action": (
            "Inspect the Recommended Next Action card, check Saved Workflows & Restart Recovery for any "
            "interrupted or paused runs, or run Verify DB Health."
        ),
        "expect": (
            "Real portfolio metrics, a 90%-cutoff confidence bar chart, and one-click Resume Workflow buttons "
            "when saved checkpoints are cleared to continue."
        ),
    },
    {
        "title": "Filing Analysis",
        "url_path": "filing-analysis",
        "purpose": (
            "Retrieves real Form 10-K filings from SEC EDGAR (AAPL, MSFT, GOOGL, AMZN, WMT), extracts 8 core "
            "annual metrics, scores 5-factor confidence, and runs deterministic financial validations."
        ),
        "action": (
            "Select companies and click 'Retrieve Latest 10-K Filings', then pick a retrieved filing and click "
            "'Extract 8 Core Financial Metrics'."
        ),
        "expect": (
            "Normalized USD and per-share values saved to SQLite with verbatim filing HTML citations, "
            "5-factor confidence tables, and Accounting Equation / Segment / YoY validation statuses."
        ),
    },
    {
        "title": "Human Review",
        "url_path": "human-review",
        "purpose": (
            "Resolves exceptions whenever an extracted metric has low confidence (<90%), ambiguity, or a failed "
            "financial validation rule that pauses the LangGraph checkpoint."
        ),
        "action": (
            "Compare the extracted figure side-by-side against the filing citation, enter a justification note "
            "if correcting or rejecting, and click Approve, Correct Value, or Reject."
        ),
        "expect": (
            "Your decision commits atomically with an append-only SHA-256 audit event while permanently preserving "
            "the original extracted number, and unblocked workflows resume cleanly."
        ),
    },
    {
        "title": "Accuracy Report",
        "url_path": "accuracy-report",
        "purpose": (
            "Benchmarks both raw automated extraction (Pre-Review) and final accepted/edited outputs (Post-Review) "
            "against official SEC EDGAR Company Facts XBRL ground truth."
        ),
        "action": (
            "Select an audit run (or All Audit Runs) and click 'Evaluate vs. SEC Facts' to run strict "
            "company CIK, US-GAAP concept, FY annual period, and unit matching."
        ),
        "expect": (
            "Separate Pre-Review vs. Post-Review accuracy and coverage denominators, interactive company/metric "
            "charts, provenance explanations, and downloadable FinovaLabs CSV/JSON reports."
        ),
    },
    {
        "title": "Audit Trail",
        "url_path": "audit-trail",
        "purpose": (
            "Provides a chronological, append-only ledger of human decisions and workflow milestones linked by "
            "sequential record IDs and SHA-256 hash chaining (tamper-evident, not absolutely tamper-proof)."
        ),
        "action": (
            "Filter by Company, UTC Date, Decision, Metric, or Workflow ID, toggle low-level telemetry if desired, "
            "and click 'Re-Verify Audit Hash Chain' or 'Download Audit Ledger JSON'."
        ),
        "expect": (
            "Immediate cryptographic integrity confirmation showing zero gaps or altered records, side-by-side "
            "Original vs. Corrected decision history, and full JSON ledger export."
        ),
    },
)


def reset_ui_session_state() -> None:
    """Safely reset browser UI/tour session preferences without deleting SQLite data."""
    keys_to_clear = (
        "fl_welcome_dismissed",
        "fl_tour_active",
        "fl_tour_step",
        "fl_active_ticker",
        "fl_active_accession",
        "fl_active_run_id",
        "last_retrieval_outcomes",
        "fa_selected_labels",
        "fa_select_all_cb",
    )
    for k in keys_to_clear:
        st.session_state.pop(k, None)


def apply_design_system(
    active_section: str,
    db_status_label: str = "SQLite Connected",
    context_summary: str | None = None,
) -> None:
    """Inject enterprise CSS, sidebar context, and persistent 'How to use FinovaLabs' help."""
    st.markdown(_ENTERPRISE_CSS, unsafe_allow_html=True)
    ctx_html = (
        f"""
        <div class="fl-sidebar-meta">
          <div class="fl-sidebar-meta-label">Workspace Context</div>
          <div class="fl-sidebar-meta-value">{escape(context_summary)}</div>
        </div>
        """
        if context_summary
        else ""
    )
    with st.sidebar:
        st.markdown(
            f"""
            <div class="fl-sidebar-brand">
              <div style="width:36px;height:36px;flex-shrink:0;">{_LOGO_SVG}</div>
              <div>
                <div class="fl-sidebar-brand-title">{escape(PRODUCT_NAME)}</div>
                <div class="fl-sidebar-brand-tag">{escape(PRODUCT_TAGLINE)}</div>
              </div>
            </div>
            {ctx_html}
            <div class="fl-sidebar-meta">
              <div class="fl-sidebar-meta-label">Database Status</div>
              <div class="fl-sidebar-meta-value">{escape(db_status_label)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("How to use FinovaLabs", expanded=False):
            st.markdown(
                """
                <ol class="fl-sidebar-help-list">
                  <li><strong>Select company:</strong> Pick tickers in Filing Analysis.</li>
                  <li><strong>Retrieve 10-K:</strong> Fetch live SEC metadata &amp; Company Facts.</li>
                  <li><strong>Extract metrics:</strong> Extract 8 core annual metrics with citations.</li>
                  <li><strong>Validate:</strong> Score 5-factor confidence (&ge;90%) &amp; financial rules.</li>
                  <li><strong>Review exceptions:</strong> Resolve paused items in Human Review.</li>
                  <li><strong>Compare with SEC facts:</strong> Run pre/post Accuracy Report.</li>
                  <li><strong>View audit report:</strong> Verify SHA-256 history in Audit Trail.</li>
                </ol>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Start guided tour",
                key="sb_start_guided_tour",
                help="Walk through Overview, Filing Analysis, Human Review, Accuracy Report, and Audit Trail one step at a time.",
                **stretch_width_kwargs(st.button),
            ):
                st.session_state["fl_tour_active"] = True
                st.session_state["fl_tour_step"] = 0
                st.rerun()

            if st.button(
                "Reset UI & Restart Tour",
                key="sb_safe_ui_reset",
                help="Safe non-destructive UI reset: clears only browser filters and tour state. Your SQLite database is untouched.",
                **stretch_width_kwargs(st.button),
            ):
                reset_ui_session_state()
                flash_feedback(
                    "info",
                    "UI filters, welcome panel, and guided tour were reset safely. Real SQLite filings, decisions, and audit records remain intact.",
                )
                st.rerun()

            st.caption(
                "Safe Restart: Closing or refreshing FinovaLabs never deletes SQLite records (`finova_labs.db`). "
                "Interrupted workflows resume automatically from saved checkpoints on Overview."
            )


def render_welcome_panel(*, allow_dismiss: bool = True) -> None:
    """Render the plain-English first-launch welcome banner when not yet dismissed."""
    if st.session_state.get("fl_welcome_dismissed", False):
        return

    st.markdown(
        f"""
        <div class="fl-welcome-card">
          <div class="fl-welcome-title">Welcome to {escape(PRODUCT_NAME)} — {escape(PRODUCT_TAGLINE)}</div>
          <p class="fl-welcome-body">
            FinovaLabs helps you audit real U.S. SEC <strong>Form 10-K</strong> filings step by step without guessing.
            Choose a supported public company (Apple, Microsoft, Alphabet, Amazon, or Walmart), pull its latest
            filing from SEC EDGAR, extract 8 standardized annual metrics with verbatim evidence, verify accounting and
            confidence rules, resolve escalated exceptions with human oversight, benchmark pre/post accuracy against
            SEC Company Facts, and verify every decision in an append-only SHA-256 audit ledger.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    w1, w2, w3 = st.columns([1.2, 1.4, 1.0])
    with w1:
        if st.button(
            "Start guided tour",
            key="welcome_start_tour",
            type="primary",
            help="Open the 5-step interactive walkthrough covering every FinovaLabs screen one at a time.",
            **stretch_width_kwargs(st.button),
        ):
            st.session_state["fl_tour_active"] = True
            st.session_state["fl_tour_step"] = 0
            st.rerun()
    with w2:
        navigate_button(
            "Step 1: Select Company ->",
            "filing-analysis",
            key="welcome_go_fa",
            primary=False,
            help_text="Jump directly to Filing Analysis to select a company and retrieve a live 10-K.",
        )
    with w3:
        if allow_dismiss and st.button(
            "Dismiss welcome",
            key="welcome_dismiss_btn",
            help="Hide this welcome panel for the current browser session (re-open anytime from 'How to use FinovaLabs' in the sidebar).",
            **stretch_width_kwargs(st.button),
        ):
            st.session_state["fl_welcome_dismissed"] = True
            st.rerun()


def render_guided_tour_panel(current_url_path: str) -> None:
    """Render the active 5-step guided tour card explaining one FinovaLabs screen at a time."""
    if not st.session_state.get("fl_tour_active", False):
        return

    total = len(_TOUR_SCREENS)
    step_idx = int(st.session_state.get("fl_tour_step", 0))
    step_idx = max(0, min(step_idx, total - 1))
    spec = _TOUR_SCREENS[step_idx]
    on_target_page = current_url_path == spec["url_path"]

    st.markdown(
        f"""
        <div class="fl-tour-card">
          <div class="fl-tour-eyebrow">Interactive Guided Tour &bull; Screen {step_idx + 1} of {total}: {escape(spec['title'])}</div>
          <h3 class="fl-tour-title">{escape(spec['title'])}</h3>
          <p class="fl-tour-body">
            <strong>What it does:</strong> {escape(spec['purpose'])}<br>
            <strong>Next action:</strong> {escape(spec['action'])}<br>
            <strong>Expected result:</strong> {escape(spec['expect'])}
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tc1, tc2, tc3, tc4 = st.columns([1.0, 1.4, 1.1, 0.9])
    with tc1:
        if st.button(
            "<- Previous",
            key=f"tour_prev_{current_url_path}",
            disabled=(step_idx == 0),
            **stretch_width_kwargs(st.button),
        ):
            st.session_state["fl_tour_step"] = max(0, step_idx - 1)
            st.rerun()
    with tc2:
        if on_target_page:
            st.caption(f"You are viewing {spec['title']} now.")
        else:
            navigate_button(
                f"Open {spec['title']} ->",
                spec["url_path"],
                key=f"tour_jump_{current_url_path}_{step_idx}",
                primary=False,
                help_text=f"Switch directly to {spec['title']} while keeping the guided tour open.",
            )
    with tc3:
        next_label = "Finish tour" if step_idx == total - 1 else "Next screen ->"
        if st.button(
            next_label,
            key=f"tour_next_{current_url_path}",
            type="primary",
            **stretch_width_kwargs(st.button),
        ):
            if step_idx >= total - 1:
                st.session_state["fl_tour_active"] = False
                flash_feedback(
                    "success",
                    "Guided tour complete. Start with Step 1 in Filing Analysis or inspect live SQLite state on Overview.",
                )
            else:
                st.session_state["fl_tour_step"] = step_idx + 1
            st.rerun()
    with tc4:
        if st.button(
            "Close tour",
            key=f"tour_close_{current_url_path}",
            **stretch_width_kwargs(st.button),
        ):
            st.session_state["fl_tour_active"] = False
            st.rerun()


def render_next_action_box(
    next_action: str,
    expected_result: str,
) -> None:
    """Render a consistent Next Action + Expected Result guidance strip on a page."""
    st.markdown(
        f"""
        <div class="fl-next-box">
          <strong>Next Action:</strong> {escape(next_action)}<br>
          <strong>Expected Result:</strong> {escape(expected_result)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_field_tooltips_popover() -> None:
    """Render an interactive glossary/tooltips popover explaining audit fields cleanly."""
    container = (
        st.popover("Field Definitions & Tooltips", help="Plain-English guide to confidence scores, evidence, reporting periods, units, validation statuses, and workflow checkpoints.")
        if hasattr(st, "popover")
        else st.expander("Field Definitions & Tooltips", expanded=False)
    )
    with container:
        st.markdown(
            f"- **Confidence Scores:** {TOOLTIP_CONFIDENCE}\n"
            f"- **Evidence:** {TOOLTIP_EVIDENCE}\n"
            f"- **Reporting Periods:** {TOOLTIP_PERIOD}\n"
            f"- **Units & Scale:** {TOOLTIP_UNIT}\n"
            f"- **Validation Statuses:** {TOOLTIP_VALIDATION}\n"
            f"- **Workflow Checkpoints:** {TOOLTIP_CHECKPOINT}"
        )


def flash_feedback(kind: str, message: str) -> None:
    """Persist a confirmation or warning banner across st.rerun()."""
    st.session_state["fl_flash_feedback"] = {"kind": kind, "message": message}


def render_flash_feedback() -> None:
    """Render and consume any queued cross-rerun confirmation banner."""
    payload = st.session_state.pop("fl_flash_feedback", None)
    if not isinstance(payload, dict):
        return
    kind = str(payload.get("kind") or "info")
    msg = str(payload.get("message") or "").strip()
    if not msg:
        return
    if kind == "success":
        st.success(msg)
    elif kind == "warning":
        st.warning(msg)
    elif kind == "error":
        st.error(msg)
    else:
        st.info(msg)


def navigate_button(
    label: str,
    url_path: str,
    *,
    key: str,
    primary: bool = True,
    help_text: str | None = None,
) -> None:
    """Render a cross-page action button wired to st.switch_page when registered."""
    btn_type = "primary" if primary else "secondary"
    if st.button(
        label,
        key=key,
        type=btn_type,
        help=help_text,
        **stretch_width_kwargs(st.button),
    ):
        pages_map = st.session_state.get("fl_pages")
        if isinstance(pages_map, dict) and url_path in pages_map:
            st.switch_page(pages_map[url_path])
        else:
            st.info(f"Open **{label.replace('→', '').strip()}** from the left sidebar.")


def render_workflow_stepper(
    active_step: int,
    *,
    companies_count: int = 0,
    filings_count: int = 0,
    metrics_count: int = 0,
    validations_count: int = 0,
    runs_count: int = 0,
    open_reviews: int = 0,
    resolved_reviews: int = 0,
    evaluations_count: int = 0,
    events_count: int = 0,
) -> None:
    """Render the 7-stage end-to-end audit workflow progress indicator."""
    steps = [
        (1, "1. Select company ->", f"{companies_count} company(s)" if companies_count else "Pick ticker", companies_count > 0),
        (2, "2. Retrieve 10-K ->", f"{filings_count} filing(s)" if filings_count else "Fetch EDGAR", filings_count > 0),
        (3, "3. Extract metrics ->", f"{metrics_count} metric(s)" if metrics_count else "8 core metrics", metrics_count > 0),
        (4, "4. Validate ->", f"{validations_count} check(s)" if validations_count else ("Checked" if runs_count else "Rules & conf."), validations_count > 0 or runs_count > 0),
        (5, "5. Review exceptions ->", f"{open_reviews} open" if open_reviews else (f"{resolved_reviews} resolved" if resolved_reviews else ("Queue clear" if runs_count else "Auto/escalate")), runs_count > 0 and open_reviews == 0),
        (6, "6. Compare with SEC facts ->", f"{evaluations_count} evaluated" if evaluations_count else "Pre vs. post", evaluations_count > 0),
        (7, "7. View audit report", f"{events_count} event(s)" if events_count else "SHA-256 log", events_count > 0 and evaluations_count > 0),
    ]
    blocks = []
    for num, label, sub, is_done in steps:
        if num == active_step:
            cls = "fl-step fl-step-active"
        elif num == 5 and open_reviews > 0:
            cls = "fl-step fl-step-alert"
        elif is_done:
            cls = "fl-step fl-step-done"
        else:
            cls = "fl-step"
        blocks.append(
            f'<div class="{cls}"><div class="fl-step-num">{escape(label)}</div>'
            f'<div>{escape(sub)}</div></div>'
        )
    st.markdown(f'<div class="fl-stepper">{"".join(blocks)}</div>', unsafe_allow_html=True)


def render_page_header(
    title: str,
    subtitle: str,
    status_label: str = "Ready",
    status_tone: str = "info",
) -> None:
    """Render the branded enterprise header banner for a FinovaLabs page."""
    badge_html = status_badge(status_label, tone=status_tone)
    st.markdown(
        f"""
        <div class="fl-header">
          <div>
            <div class="fl-header-eyebrow">{escape(PRODUCT_NAME)} &bull; {escape(PRODUCT_TAGLINE)}</div>
            <h1 class="fl-header-title">{escape(title)}</h1>
            <p class="fl-header-subtitle">{escape(subtitle)}</p>
          </div>
          <div>{badge_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_cards(cards: Sequence[dict[str, str]]) -> None:
    """Render a responsive grid of KPI/configuration cards."""
    items_html = []
    for card in cards:
        items_html.append(
            f"""
            <div class="fl-card">
              <div class="fl-kpi-label">{escape(card.get("label", ""))}</div>
              <div class="fl-kpi-value">{escape(card.get("value", ""))}</div>
              <div class="fl-kpi-detail">{escape(card.get("detail", ""))}</div>
            </div>
            """
        )
    st.markdown(
        f'<div class="fl-grid">{"".join(items_html)}</div>',
        unsafe_allow_html=True,
    )


def render_info_card(
    title: str,
    body: str,
    badge_label: str | None = None,
    badge_tone: str = "info",
) -> None:
    """Render a polished white enterprise card with optional status badge."""
    badge_html = status_badge(badge_label, tone=badge_tone) if badge_label else ""
    st.markdown(
        f"""
        <div class="fl-card" style="margin-bottom:1rem;">
          <div class="fl-card-header">
            <h3 class="fl-card-title">{escape(title)}</h3>
            {badge_html}
          </div>
          <p class="fl-card-body">{escape(body)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(
    title: str,
    description: str,
    badge_label: str = "No Data Yet",
    next_step: str | None = None,
) -> None:
    """Render a realistic empty state when SQLite has no records for a view."""
    next_html = (
        f'<div class="fl-empty-next">{escape(next_step)}</div>'
        if next_step
        else ""
    )
    st.markdown(
        f"""
        <div class="fl-empty">
          <div class="fl-empty-badge">{escape(badge_label)}</div>
          <h3 class="fl-empty-title">{escape(title)}</h3>
          <p class="fl-empty-desc">{escape(description)}</p>
          {next_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_error_banner(
    title: str,
    message: str,
    hint: str | None = None,
) -> None:
    """Render a clear, non-crashing error alert box."""
    hint_html = (
        f'<div class="fl-error-hint"><strong>Recommended action:</strong> {escape(hint)}</div>'
        if hint
        else ""
    )
    st.markdown(
        f"""
        <div class="fl-error-box">
          <div class="fl-error-title">{escape(title)}</div>
          <div>{escape(message)}</div>
          {hint_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[tuple[str, str] | str]],
    right_align_cols: set[int] | None = None,
    header_tooltips: dict[str, str] | None = None,
) -> None:
    """Render a modern HTML table with optional right-alignment and header tooltips.

    Each cell may be a plain string (HTML-escaped) or a ``(label, tone)`` tuple
    to render a status badge pill.
    """
    align_right = right_align_cols or set()
    tips = {**FIELD_TOOLTIPS, **(header_tooltips or {})}
    th_parts = []
    for idx, h in enumerate(headers):
        tip = tips.get(h)
        inner = (
            f'<abbr class="fl-tip" title="{escape(tip)}">{escape(h)}</abbr>'
            if tip
            else escape(h)
        )
        cls_attr = ' class="fl-num"' if idx in align_right else ""
        th_parts.append(f"<th{cls_attr}>{inner}</th>")
    head_html = "".join(th_parts)
    body_rows = []
    for row in rows:
        cells = []
        for idx, cell in enumerate(row):
            cls_attr = ' class="fl-num"' if idx in align_right else ""
            if isinstance(cell, tuple):
                cells.append(f"<td{cls_attr}>{status_badge(cell[0], tone=cell[1])}</td>")
            else:
                cells.append(f"<td{cls_attr}>{escape(cell)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    st.markdown(
        f"""
        <div class="fl-table-wrap">
          <table class="fl-table">
            <thead><tr>{head_html}</tr></thead>
            <tbody>{"".join(body_rows)}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def safe_execute(operation: Callable[[], T], context: str) -> T | None:
    """Execute a UI or database operation with logging and friendly error display."""
    try:
        return operation()
    except FinovaError as exc:
        logger.error("Application error during %s: %s", context, exc)
        render_error_banner(
            title=f"Unable to complete {context}",
            message=exc.message,
            hint=exc.hint,
        )
    except Exception as exc:  # pragma: no cover - defensive UI boundary
        logger.exception("Unexpected error during %s", context)
        render_error_banner(
            title=f"Unexpected error during {context}",
            message=str(exc),
            hint="Check data/logs/finova_labs.log for full diagnostic details.",
        )
    return None


def render_plotly_chart(
    fig: Any,
    *,
    title: str | None = None,
    key: str | None = None,
    height: int = 330,
) -> None:
    """Style and render an interactive Plotly chart inside an enterprise white card."""
    fig.update_layout(
        title=dict(
            text=title or "",
            font=dict(size=14, color="#0B1E36", family="Inter, Segoe UI, sans-serif"),
            x=0.01,
            xanchor="left",
        )
        if title
        else None,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#334155", family="Inter, Segoe UI, sans-serif", size=12),
        margin=dict(l=16, r=16, t=46 if title else 24, b=20),
        height=height,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            font=dict(size=11, color="#334155"),
        ),
        hoverlabel=dict(bgcolor="#0B1E36", font_color="#FFFFFF", bordercolor="#1D4ED8"),
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor="#E2E8F0",
        tickfont=dict(color="#334155", size=11),
        title_font=dict(color="#0F172A", size=12),
    )
    fig.update_yaxes(
        gridcolor="#F1F5F9",
        zerolinecolor="#E2E8F0",
        tickfont=dict(color="#334155", size=11),
        title_font=dict(color="#0F172A", size=12),
    )
    with st.container(border=True):
        st.plotly_chart(
            fig,
            key=key,
            theme=None,
            config={"displayModeBar": False},
            **stretch_width_kwargs(st.plotly_chart),
        )


def stretch_width_kwargs(widget_fn: Callable[..., Any]) -> dict[str, Any]:
    """Return width='stretch' on newer Streamlit or use_container_width=True on >=1.39."""
    try:
        params = inspect.signature(widget_fn).parameters
    except (TypeError, ValueError):
        return {"use_container_width": True}
    if "width" in params:
        return {"width": "stretch"}
    return {"use_container_width": True}


def render_footer(note: str = "MINEARENA PS-01 • Enterprise Foundation") -> None:
    """Render the consistent FinovaLabs footer."""
    st.markdown(
        f"""
        <div class="fl-footer">
          <span><strong>{escape(PRODUCT_NAME)}</strong> &mdash; {escape(PRODUCT_TAGLINE)}</span>
          <span>{escape(note)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
