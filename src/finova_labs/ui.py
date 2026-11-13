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
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" fill="none">
  <rect x="0.75" y="0.75" width="34.5" height="34.5" rx="4" fill="#102136" stroke="#284263" stroke-width="1.5"/>
  <rect x="8" y="9" width="3.5" height="18" rx="0.75" fill="#F7F6F2"/>
  <rect x="14.5" y="9" width="13.5" height="3" rx="0.75" fill="#F7F6F2"/>
  <rect x="14.5" y="16.5" width="10" height="3" rx="0.75" fill="#C9D3E0"/>
  <rect x="14.5" y="24" width="6.5" height="3" rx="0.75" fill="#8EA2BC"/>
  <rect x="24" y="22.5" width="4" height="4.5" rx="0.75" fill="#2F66C8"/>
</svg>
""".strip()

_MARK_MINI_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="16" height="16" fill="none" style="vertical-align:-2px;">
  <rect x="1" y="1" width="18" height="18" rx="3" fill="#0C1B2E"/>
  <rect x="4.5" y="4.5" width="2.2" height="11" fill="#FFFFFF"/>
  <rect x="8.2" y="4.5" width="7.3" height="2" fill="#FFFFFF"/>
  <rect x="8.2" y="9" width="5.3" height="2" fill="#CBD5E1"/>
  <rect x="12.5" y="13" width="3" height="2.5" fill="#2F66C8"/>
</svg>
""".strip()

# Public constants for branding assets
LOGO_SVG = _LOGO_SVG
MARK_MINI_SVG = _MARK_MINI_SVG

_FAVICON_URI = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_LOGO_SVG.encode("utf-8")).decode("ascii")
)

_TONE_CLASSES = {"success", "warning", "danger", "info", "neutral"}

_ENTERPRISE_CSS = """
<style>
  :root {
    /* Institutional Financial Research Palette */
    --fl-canvas: #F7F6F2;
    --fl-surface: #FFFFFF;
    --fl-surface-subtle: #F1EFE9;
    --fl-sidebar-bg: #0C1A2B;
    --fl-sidebar-surface: #13253B;
    --fl-sidebar-border: #223854;

    --fl-ink-900: #0C1B2E;
    --fl-ink-700: #273447;
    --fl-ink-600: #4A586B;
    --fl-ink-500: #596779;

    /* Single Restrained Cobalt Accent */
    --fl-cobalt: #1E4B9A;
    --fl-cobalt-hover: #163B7A;
    --fl-cobalt-tint: #EEF3FA;
    --fl-cobalt-border: #C5D4EC;

    /* Muted Slate-Stone Hairlines */
    --fl-border: #DDDAD2;
    --fl-border-strong: #C5C1B6;

    /* Accessible Semantic Status Tokens */
    --fl-ok-ink: #0E5A3E;
    --fl-ok-bg: #EDF6F1;
    --fl-ok-bd: #B6DEC9;
    --fl-warn-ink: #854D0E;
    --fl-warn-bg: #FCF6E8;
    --fl-warn-bd: #E8D29B;
    --fl-err-ink: #8B1D1D;
    --fl-err-bg: #FBF0F0;
    --fl-err-bd: #E5BDBD;

    /* Strict 8px Spacing Scale & Layout Grid */
    --fl-sp-1: 8px;
    --fl-sp-2: 16px;
    --fl-sp-3: 24px;
    --fl-sp-4: 32px;
    --fl-sp-5: 40px;
    --fl-sp-6: 48px;
    --fl-sp-8: 64px;
    --fl-radius-sm: 4px;
    --fl-radius: 6px;
    --fl-max-width: 1200px;
  }

  .stApp {
    background-color: var(--fl-canvas);
    color: var(--fl-ink-900);
    font-family: "IBM Plex Sans", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-feature-settings: "cv02", "cv03", "cv04", "cv11";
    max-width: 100%;
  }

  .stApp *,
  .stApp *::before,
  .stApp *::after {
    box-sizing: border-box;
  }

  [data-testid="stAppViewContainer"],
  [data-testid="stMain"] {
    max-width: 100%;
    background-color: var(--fl-canvas);
  }

  header[data-testid="stHeader"] {
    background-color: rgba(247, 246, 242, 0.92);
    border-bottom: 1px solid var(--fl-border);
  }

  .block-container,
  [data-testid="stMainBlockContainer"] {
    padding: var(--fl-sp-8) var(--fl-sp-3) var(--fl-sp-4) var(--fl-sp-3) !important;
    max-width: var(--fl-max-width) !important;
    width: 100% !important;
    margin: 0 auto !important;
  }

  /* Prevent flex/grid children & long strings (URLs, accession numbers, quotes) from blowing out width */
  [data-testid="stVerticalBlock"],
  [data-testid="stColumn"] {
    min-width: 0 !important;
  }

  [data-testid="stHorizontalBlock"] {
    gap: var(--fl-sp-2);
    align-items: stretch;
  }

  [data-testid="stMarkdownContainer"],
  [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] li,
  [data-testid="stMarkdownContainer"] a,
  .fl-header-title,
  .fl-header-subtitle,
  .fl-card-title,
  .fl-card-body,
  .fl-kpi-value,
  .fl-kpi-detail,
  .fl-evidence-box,
  .fl-next-box,
  .fl-welcome-title,
  .fl-welcome-body,
  .fl-tour-title,
  .fl-tour-body,
  .fl-glossary-item,
  .fl-error-box,
  .fl-action-banner,
  .fl-footer {
    overflow-wrap: anywhere;
    word-break: break-word;
    min-width: 0;
  }

  [data-testid="stMarkdownContainer"] code,
  [data-testid="stMarkdownContainer"] pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
    max-width: 100%;
  }

  /* Restrained matte ink-navy sidebar (no gradients, no neon) */
  [data-testid="stSidebar"] {
    background: var(--fl-sidebar-bg);
    border-right: 1px solid var(--fl-sidebar-border);
    color: #E2E6EC;
    max-width: 100vw;
  }

  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label {
    color: #D7DEE8;
  }

  [data-testid="stSidebarNav"] {
    padding-top: var(--fl-sp-1);
    padding-bottom: var(--fl-sp-2);
    border-bottom: 1px solid var(--fl-sidebar-border);
    margin-bottom: var(--fl-sp-2);
  }

  [data-testid="stSidebarNav"] a {
    border-radius: var(--fl-radius-sm);
    margin: 2px var(--fl-sp-1);
    padding: var(--fl-sp-1) var(--fl-sp-2);
    transition: background-color 0.12s ease, border-color 0.12s ease;
    border-left: 2px solid transparent;
    min-height: 40px;
    display: flex;
    align-items: center;
  }

  [data-testid="stSidebarNav"] a:hover {
    background-color: var(--fl-sidebar-surface);
  }

  [data-testid="stSidebarNav"] a[aria-current="page"] {
    background-color: var(--fl-sidebar-surface);
    border-left: 2px solid #5B8CE0;
    font-weight: 600;
  }

  [data-testid="stSidebarNav"] span {
    color: #F4F6F9 !important;
    font-size: 0.89rem;
    white-space: normal;
    line-height: 1.3;
    letter-spacing: -0.005em;
  }

  [data-testid="stSidebarCollapseButton"] svg {
    fill: #B8C4D4;
  }

  /* Restrained institutional buttons with single cobalt accent & safe multi-line wrapping */
  .stButton > button,
  .stDownloadButton > button {
    border-radius: var(--fl-radius-sm);
    border: 1px solid var(--fl-border-strong);
    background-color: var(--fl-surface);
    color: var(--fl-ink-900);
    font-weight: 600;
    font-size: 0.86rem;
    padding: var(--fl-sp-1) var(--fl-sp-2);
    min-height: 40px;
    height: auto;
    line-height: 1.3;
    white-space: normal;
    word-break: break-word;
    max-width: 100%;
    box-shadow: none;
    transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
  }

  .stButton > button:hover,
  .stDownloadButton > button:hover {
    border-color: var(--fl-cobalt);
    color: var(--fl-cobalt);
    background-color: var(--fl-cobalt-tint);
  }

  .stButton > button[kind="primary"] {
    background-color: var(--fl-cobalt);
    border-color: var(--fl-cobalt);
    color: #FFFFFF;
  }

  .stButton > button[kind="primary"]:hover {
    background-color: var(--fl-cobalt-hover);
    border-color: var(--fl-cobalt-hover);
    color: #FFFFFF;
  }

  /* Subtle institutional expanders & tabs */
  [data-testid="stExpander"] {
    background-color: var(--fl-surface);
    border: 1px solid var(--fl-border) !important;
    border-radius: var(--fl-radius) !important;
    box-shadow: none !important;
  }

  [data-testid="stSidebar"] [data-testid="stExpander"] {
    background-color: var(--fl-sidebar-surface);
    border-color: var(--fl-sidebar-border) !important;
  }

  [data-baseweb="tab-list"] {
    flex-wrap: wrap !important;
    gap: var(--fl-sp-1);
    height: auto !important;
    border-bottom: 1px solid var(--fl-border);
  }

  [data-baseweb="tab"] {
    height: auto !important;
    min-height: 40px;
    padding: var(--fl-sp-1) var(--fl-sp-2) !important;
    white-space: normal !important;
    font-weight: 600;
  }

  /* Viewport-bounded dialogs, popovers & select dropdowns */
  [data-baseweb="popover"],
  [data-baseweb="menu"],
  [data-testid="stDialog"] [role="dialog"] {
    max-width: calc(100vw - 32px) !important;
    max-height: calc(100vh - 32px) !important;
    overflow: auto;
  }

  [data-baseweb="menu"] li,
  [data-baseweb="select"] span {
    white-space: normal !important;
    overflow-wrap: anywhere;
  }

  /* Plotly chart container responsiveness */
  [data-testid="stPlotlyChart"],
  [data-testid="stPlotlyChart"] > div,
  .js-plotly-plot,
  .plot-container {
    max-width: 100% !important;
    width: 100% !important;
  }

  .fl-sidebar-brand {
    display: flex;
    align-items: center;
    gap: var(--fl-sp-2);
    padding: var(--fl-sp-2);
    margin: var(--fl-sp-1) 0 var(--fl-sp-2) 0;
    background: var(--fl-sidebar-surface);
    border: 1px solid var(--fl-sidebar-border);
    border-radius: var(--fl-radius);
  }

  .fl-wordmark {
    display: inline-flex;
    align-items: baseline;
    gap: 2px;
    font-size: 1.02rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    line-height: 1.15;
  }

  .fl-wm-primary {
    font-weight: 700;
    color: #FFFFFF !important;
  }

  .fl-wm-secondary {
    font-weight: 400;
    color: #B4C2D4 !important;
  }

  .fl-sidebar-brand-tag {
    font-size: 0.7rem;
    color: #9FB0C5 !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    line-height: 1.35;
    margin-top: 4px;
  }

  .fl-sidebar-meta {
    background: var(--fl-sidebar-surface);
    border: 1px solid var(--fl-sidebar-border);
    border-radius: var(--fl-radius);
    padding: var(--fl-sp-2);
    margin-top: var(--fl-sp-1);
    font-size: 0.81rem;
  }

  .fl-sidebar-meta-label {
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-size: 0.7rem;
    color: #9FB0C5 !important;
    font-weight: 600;
    margin-bottom: var(--fl-sp-1);
  }

  .fl-sidebar-meta-value {
    color: #F4F6F9 !important;
    font-weight: 500;
    line-height: 1.45;
  }

  /* Compact Editorial Page Masthead (no oversized gradient hero banner) */
  .fl-header {
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--fl-border-strong);
    border-radius: 0;
    padding: 0 0 var(--fl-sp-2) 0;
    margin-bottom: var(--fl-sp-2);
    color: var(--fl-ink-900);
    box-shadow: none;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-end;
    gap: var(--fl-sp-2);
  }

  .fl-header-eyebrow {
    display: flex;
    align-items: center;
    gap: var(--fl-sp-1);
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--fl-cobalt);
    margin-bottom: var(--fl-sp-1);
  }

  .fl-header-title {
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--fl-ink-900);
    margin: 0;
    line-height: 1.2;
  }

  .fl-header-subtitle {
    font-size: 0.91rem;
    color: var(--fl-ink-600);
    margin: 6px 0 0 0;
    max-width: 74ch;
    line-height: 1.48;
  }

  /* 7-stage Hairline Segmented Workflow Ribbon */
  .fl-stepper {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 0;
    border-top: 1px solid var(--fl-border);
    border-left: 1px solid var(--fl-border);
    border-radius: var(--fl-radius);
    overflow: hidden;
    background: var(--fl-surface);
    margin-bottom: var(--fl-sp-1);
  }

  .fl-step {
    background: var(--fl-surface);
    border-right: 1px solid var(--fl-border);
    border-bottom: 1px solid var(--fl-border);
    border-radius: 0;
    padding: var(--fl-sp-1);
    font-size: 0.74rem;
    color: var(--fl-ink-500);
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 4px;
    line-height: 1.3;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .fl-step-active {
    background: var(--fl-cobalt-tint);
    box-shadow: inset 0 2px 0 0 var(--fl-cobalt);
    color: var(--fl-ink-900);
    font-weight: 600;
  }

  .fl-step-done {
    background: var(--fl-ok-bg);
    color: var(--fl-ok-ink);
  }

  .fl-step-alert {
    background: var(--fl-warn-bg);
    color: var(--fl-warn-ink);
  }

  .fl-step-fail {
    background: var(--fl-err-bg);
    color: var(--fl-err-ink);
  }

  /* Compact 4-Category Hairline Audit Status Bar */
  .fl-work-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1px;
    background: var(--fl-border);
    border: 1px solid var(--fl-border);
    border-radius: var(--fl-radius);
    overflow: hidden;
    margin: 0 0 var(--fl-sp-2) 0;
  }

  .fl-work-pill {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--fl-sp-1);
    padding: var(--fl-sp-1) var(--fl-sp-2);
    border: none;
    border-radius: 0;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--fl-surface);
    color: var(--fl-ink-700);
    font-variant-numeric: tabular-nums lining-nums;
    min-width: 0;
    flex-wrap: wrap;
  }

  .fl-work-label {
    display: inline-flex;
    align-items: center;
    gap: var(--fl-sp-1);
    min-width: 0;
  }

  .fl-work-dot {
    width: 6px;
    height: 6px;
    border-radius: 1px;
    background: currentColor;
    flex-shrink: 0;
  }

  .fl-work-pill-pending {
    background: var(--fl-warn-bg);
    color: var(--fl-warn-ink);
  }

  .fl-work-pill-completed {
    background: var(--fl-ok-bg);
    color: var(--fl-ok-ink);
  }

  .fl-work-pill-failed {
    background: var(--fl-err-bg);
    color: var(--fl-err-ink);
  }

  .fl-work-pill-human {
    background: var(--fl-cobalt-tint);
    color: var(--fl-cobalt);
  }

  .fl-work-pill-muted {
    background: var(--fl-surface);
    color: var(--fl-ink-500);
  }

  /* Inline Contextual Glossary Guide */
  .fl-glossary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(224px, 100%), 1fr));
    gap: var(--fl-sp-2);
    margin: var(--fl-sp-1) 0 var(--fl-sp-2) 0;
  }

  .fl-glossary-item {
    background: var(--fl-surface-subtle);
    border: 1px solid var(--fl-border);
    border-left: 3px solid var(--fl-cobalt);
    border-radius: var(--fl-radius-sm);
    padding: var(--fl-sp-1) var(--fl-sp-2);
    font-size: 0.81rem;
    line-height: 1.45;
    color: var(--fl-ink-700);
  }

  .fl-glossary-item strong {
    color: var(--fl-ink-900);
    display: block;
    margin-bottom: 4px;
    font-size: 0.82rem;
  }

  .fl-step-num {
    font-size: 0.69rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.94;
    font-weight: 700;
  }

  /* Restrained Welcome Brief, Tour Panel & Guidance Callout */
  .fl-welcome-card {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-left: 3px solid var(--fl-cobalt);
    border-radius: var(--fl-radius);
    padding: var(--fl-sp-2) var(--fl-sp-3);
    margin-bottom: var(--fl-sp-2);
    color: var(--fl-ink-900);
  }

  .fl-welcome-title {
    font-size: 1rem;
    font-weight: 700;
    color: var(--fl-ink-900);
    letter-spacing: -0.01em;
    margin: 0 0 var(--fl-sp-1) 0;
  }

  .fl-welcome-body {
    font-size: 0.88rem;
    color: var(--fl-ink-700);
    line-height: 1.55;
    margin: 0;
  }

  .fl-tour-card {
    background: var(--fl-sidebar-bg);
    border: 1px solid var(--fl-sidebar-border);
    border-left: 3px solid var(--fl-cobalt);
    border-radius: var(--fl-radius);
    padding: var(--fl-sp-2) var(--fl-sp-3);
    margin-bottom: var(--fl-sp-2);
    color: #F4F6F9;
  }

  .fl-tour-eyebrow {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #9EB8DD;
    margin-bottom: 4px;
  }

  .fl-tour-title {
    font-size: 1rem;
    font-weight: 700;
    color: #FFFFFF;
    margin: 0 0 var(--fl-sp-1) 0;
  }

  .fl-tour-body {
    font-size: 0.87rem;
    color: #D7DEE8;
    line-height: 1.55;
    margin: 0;
  }

  .fl-next-box {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-left: 3px solid var(--fl-cobalt);
    border-radius: var(--fl-radius-sm);
    padding: var(--fl-sp-2);
    margin-bottom: var(--fl-sp-2);
    font-size: 0.87rem;
    color: var(--fl-ink-700);
    line-height: 1.5;
  }

  .fl-tip {
    text-decoration: none;
    border-bottom: 1px dotted var(--fl-ink-500);
    cursor: help;
  }

  .fl-sidebar-help-list {
    margin: var(--fl-sp-1) 0 var(--fl-sp-1) var(--fl-sp-2);
    padding: 0;
    font-size: 0.79rem;
    color: #D7DEE8 !important;
    line-height: 1.5;
  }

  .fl-sidebar-help-list li {
    margin-bottom: 4px;
  }

  /* Unified Institutional Summary Ledger Bar (replaces detached rounded KPI tile cards) */
  .fl-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1px;
    background: var(--fl-border);
    border: 1px solid var(--fl-border);
    border-radius: var(--fl-radius);
    overflow: hidden;
    margin-bottom: var(--fl-sp-2);
    align-items: stretch;
  }

  .fl-card {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-radius: var(--fl-radius);
    padding: var(--fl-sp-2) var(--fl-sp-3);
    box-shadow: none;
    min-width: 0;
  }

  .fl-grid > .fl-card {
    border: none;
    border-radius: 0;
    height: 100%;
    min-height: 112px;
    padding: var(--fl-sp-2);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .fl-info-card {
    border-left: 3px solid var(--fl-cobalt);
    margin-bottom: var(--fl-sp-2);
  }

  .fl-kpi-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--fl-ink-500);
    margin-bottom: var(--fl-sp-1);
  }

  .fl-kpi-value {
    font-size: 1.42rem;
    font-weight: 700;
    color: var(--fl-ink-900);
    font-variant-numeric: tabular-nums lining-nums;
    letter-spacing: -0.02em;
    line-height: 1.2;
  }

  .fl-kpi-detail {
    font-size: 0.8rem;
    color: var(--fl-ink-500);
    margin-top: var(--fl-sp-1);
    line-height: 1.4;
  }

  .fl-card-header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: var(--fl-sp-1);
    margin-bottom: var(--fl-sp-1);
  }

  .fl-card-title {
    font-size: 0.98rem;
    font-weight: 700;
    color: var(--fl-ink-900);
    letter-spacing: -0.01em;
    margin: 0;
  }

  .fl-card-body {
    font-size: 0.89rem;
    color: var(--fl-ink-700);
    line-height: 1.55;
    margin: 0;
  }

  .fl-section-title {
    font-size: 0.98rem;
    font-weight: 700;
    color: var(--fl-ink-900);
    letter-spacing: -0.015em;
    margin: var(--fl-sp-4) 0 var(--fl-sp-2) 0;
    padding-bottom: var(--fl-sp-1);
    border-bottom: 1px solid var(--fl-border);
  }

  .fl-chart-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--fl-sp-1);
    padding-bottom: var(--fl-sp-1);
    border-bottom: 1px solid var(--fl-border);
  }

  .fl-chart-title {
    font-size: 0.88rem;
    font-weight: 700;
    color: var(--fl-ink-900);
    letter-spacing: -0.01em;
    line-height: 1.35;
  }

  /* Restraint-first Empty State */
  .fl-empty {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-radius: var(--fl-radius);
    padding: var(--fl-sp-4) var(--fl-sp-3);
    text-align: center;
    margin-bottom: var(--fl-sp-3);
  }

  .fl-empty-badge {
    display: inline-block;
    padding: 4px 8px;
    border-radius: var(--fl-radius-sm);
    background: var(--fl-cobalt-tint);
    color: var(--fl-cobalt);
    border: 1px solid var(--fl-cobalt-border);
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: var(--fl-sp-1);
  }

  .fl-empty-title {
    font-size: 1.04rem;
    font-weight: 700;
    color: var(--fl-ink-900);
    margin: 0 0 var(--fl-sp-1) 0;
  }

  .fl-empty-desc {
    font-size: 0.89rem;
    color: var(--fl-ink-600);
    max-width: 58ch;
    margin: 0 auto;
    line-height: 1.55;
  }

  .fl-empty-next {
    margin-top: var(--fl-sp-2);
    font-size: 0.84rem;
    color: var(--fl-ink-900);
    font-weight: 600;
  }

  /* Clear Error Banner */
  .fl-error-box {
    background: var(--fl-err-bg);
    border: 1px solid var(--fl-err-bd);
    border-left: 3px solid var(--fl-err-ink);
    border-radius: var(--fl-radius-sm);
    padding: var(--fl-sp-2);
    margin-bottom: var(--fl-sp-2);
    color: var(--fl-err-ink);
  }

  .fl-error-title {
    font-weight: 700;
    font-size: 0.94rem;
    margin-bottom: 4px;
  }

  .fl-error-hint {
    margin-top: var(--fl-sp-1);
    font-size: 0.84rem;
    color: var(--fl-err-ink);
  }

  /* Semantic Status Tags (flat institutional tags, no excessive rounding) */
  .fl-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px;
    border-radius: var(--fl-radius-sm);
    font-size: 0.74rem;
    font-weight: 600;
    letter-spacing: 0.015em;
    line-height: 1.25;
    white-space: nowrap;
    max-width: 100%;
    border: 1px solid transparent;
  }

  .fl-badge-dot {
    width: 6px;
    height: 6px;
    border-radius: 1px;
    background: currentColor;
    flex-shrink: 0;
  }

  .fl-badge-success {
    color: var(--fl-ok-ink);
    background: var(--fl-ok-bg);
    border-color: var(--fl-ok-bd);
  }

  .fl-badge-warning {
    color: var(--fl-warn-ink);
    background: var(--fl-warn-bg);
    border-color: var(--fl-warn-bd);
  }

  .fl-badge-danger {
    color: var(--fl-err-ink);
    background: var(--fl-err-bg);
    border-color: var(--fl-err-bd);
  }

  .fl-badge-info {
    color: var(--fl-cobalt);
    background: var(--fl-cobalt-tint);
    border-color: var(--fl-cobalt-border);
  }

  .fl-badge-neutral {
    color: var(--fl-ink-600);
    background: var(--fl-surface-subtle);
    border-color: var(--fl-border);
  }

  /* Aligned Financial Research Ledger Tables */
  .fl-table-wrap {
    background: var(--fl-surface);
    border: 1px solid var(--fl-border);
    border-radius: var(--fl-radius);
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    max-width: 100%;
    box-shadow: none;
    margin-bottom: var(--fl-sp-3);
  }

  .fl-table-wrap::-webkit-scrollbar {
    height: 6px;
  }

  .fl-table-wrap::-webkit-scrollbar-track {
    background: var(--fl-surface-subtle);
  }

  .fl-table-wrap::-webkit-scrollbar-thumb {
    background: var(--fl-border-strong);
    border-radius: 3px;
  }

  .fl-table {
    width: 100%;
    min-width: 680px;
    border-collapse: collapse;
    font-size: 0.86rem;
    text-align: left;
  }

  .fl-table thead th {
    background: var(--fl-surface-subtle);
    color: var(--fl-ink-900);
    font-weight: 600;
    font-size: 0.73rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 10px 14px;
    border-bottom: 1px solid var(--fl-border-strong);
    white-space: nowrap !important;
    word-break: keep-all !important;
    line-height: 1.35;
    vertical-align: middle;
  }

  .fl-table tbody td {
    padding: 10px 14px;
    border-bottom: 1px solid #ECEAE3;
    color: var(--fl-ink-700);
    vertical-align: middle;
    font-variant-numeric: tabular-nums lining-nums;
    white-space: nowrap;
  }

  .fl-table thead th:first-child,
  .fl-table tbody td:first-child {
    font-weight: 600;
    color: var(--fl-ink-900);
  }

  .fl-table tbody td.fl-num,
  .fl-table thead th.fl-num {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums lining-nums;
  }

  .fl-evidence-box {
    background: var(--fl-surface-subtle);
    border: 1px solid var(--fl-border);
    border-left: 3px solid var(--fl-cobalt);
    border-radius: var(--fl-radius-sm);
    padding: var(--fl-sp-2);
    font-size: 0.86rem;
    color: var(--fl-ink-900);
    line-height: 1.5;
    margin-top: var(--fl-sp-1);
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .fl-action-banner {
    background: var(--fl-surface);
    border: 1px solid var(--fl-cobalt-border);
    border-left: 3px solid var(--fl-cobalt);
    border-radius: var(--fl-radius);
    padding: var(--fl-sp-2);
    margin-bottom: var(--fl-sp-2);
  }

  .fl-action-banner-warning {
    border-color: var(--fl-warn-bd);
    border-left-color: var(--fl-warn-ink);
    background: var(--fl-warn-bg);
  }

  .fl-action-banner-success {
    border-color: var(--fl-ok-bd);
    border-left-color: var(--fl-ok-ink);
    background: var(--fl-ok-bg);
  }

  .fl-table tbody tr:last-child td {
    border-bottom: none;
  }

  .fl-table tbody tr:hover {
    background: #FAF9F5;
  }

  .fl-footer {
    margin-top: var(--fl-sp-4);
    padding-top: var(--fl-sp-2);
    border-top: 1px solid var(--fl-border-strong);
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: var(--fl-sp-1);
    font-size: 0.78rem;
    color: var(--fl-ink-500);
  }

  /* Breakpoints tuned for 1440 / 1280 / 1024 / 768 tablet / 390 mobile */
  @media (max-width: 1200px) {
    .fl-stepper {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .fl-work-strip {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 1080px) {
    .block-container,
    [data-testid="stMainBlockContainer"] {
      padding: var(--fl-sp-8) var(--fl-sp-2) var(--fl-sp-3) var(--fl-sp-2) !important;
    }
    .fl-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    [data-testid="stHorizontalBlock"] {
      flex-wrap: wrap !important;
      gap: var(--fl-sp-2) !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      flex: 1 1 240px !important;
      min-width: min(240px, 100%) !important;
      width: auto !important;
    }
    [data-testid="stColumn"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      flex: 1 1 120px !important;
      min-width: min(120px, 100%) !important;
    }
  }

  @media (max-width: 768px) {
    .block-container,
    [data-testid="stMainBlockContainer"] {
      padding: var(--fl-sp-8) var(--fl-sp-2) var(--fl-sp-3) var(--fl-sp-2) !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    [data-testid="stColumn"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      flex: 1 1 100% !important;
      width: 100% !important;
      min-width: 100% !important;
      max-width: 100% !important;
    }
    .fl-stepper {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .fl-work-strip,
    .fl-grid,
    .fl-glossary-grid {
      grid-template-columns: 1fr;
    }
    .fl-grid > .fl-card {
      min-height: 0;
    }
    .fl-header {
      padding: 0 0 var(--fl-sp-2) 0;
    }
    .fl-header-title {
      font-size: 1.3rem;
    }
    .fl-card {
      padding: var(--fl-sp-2);
    }
    .fl-empty {
      padding: var(--fl-sp-3) var(--fl-sp-2);
    }
  }

  @media (max-width: 540px) {
    .block-container,
    [data-testid="stMainBlockContainer"] {
      padding: var(--fl-sp-8) var(--fl-sp-1) var(--fl-sp-3) var(--fl-sp-1) !important;
    }
    .fl-stepper {
      grid-template-columns: 1fr;
    }
    .fl-kpi-value {
      font-size: 1.28rem;
    }
    .fl-table {
      font-size: 0.82rem;
    }
    .fl-table thead th,
    .fl-table tbody td {
      padding: var(--fl-sp-1);
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
    "APPROVED": "Analyst Approved",
    "CORRECTED": "Analyst Corrected",
    "EDITED": "Analyst Corrected",
    "REVIEW_REQUIRED": "Pending Review",
    "PAUSED_FOR_REVIEW": "Pending Review",
    "COMPLETED_WITH_REJECTIONS": "Completed (With Rejections)",
    "COMPLETED": "Completed",
    "INTERRUPTED": "Paused (Saved)",
    "RUNNING": "In Progress",
    "PENDING": "Pending",
    "FAILED": "Failed Check",
    "FAIL": "Failed Check",
    "WARNING": "Alert / Check",
    "PASS": "Passed",
    "OPEN": "Pending Review",
    "REJECTED": "Analyst Rejected",
    "EXTRACTED": "Extracted",
    "AMBIGUOUS": "Needs Clarification",
    "MISSING": "Missing in Filing",
    "RETRIEVED": "Retrieved",
    "EXACT_MATCH": "Exact Match",
    "MATCH_FOUND": "Matched",
    "MISMATCH": "Failed Match",
    "UNMATCHED_RECORD": "Unmatched",
    "PERIOD_MISMATCH": "Period Mismatch",
    "UNIT_MISMATCH": "Unit Mismatch",
    "UNAVAILABLE_REFERENCE": "No SEC Reference",
    "NOT_APPLICABLE": "Not Applicable",
    "NOT_REQUIRED": "Not Required",
}


def humanize_status(status: str | None) -> str:
    """Convert internal enum tokens into plain-English financial audit labels."""
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
    "Confidence Score (0%–100%): Certainty rating across 5 plain checks — Line-Item Match (25%), "
    "Fiscal Period Match (25%), Unit & Scale Accuracy (20%), Supporting 10-K Quote (20%), and "
    "Cross-Check Agreement (10%). Anything below 90% pauses automatically for analyst sign-off."
)
TOOLTIP_EVIDENCE = (
    "Evidence: Exact sentence or table line quoted directly from the company's SEC 10-K filing, "
    "along with the table location and official SEC EDGAR filing link."
)
TOOLTIP_PERIOD = (
    "Reporting Period: Full fiscal year date range (for revenue, income, cash flow, EPS) or fiscal "
    "year-end balance-sheet date. Quarterly or partial-year numbers are never mixed in."
)
TOOLTIP_UNIT = (
    "Units & Scale: Standardized to full U.S. Dollars (USD) or Dollars per Share (USD/shares) from "
    "the 10-K statement multiplier (such as 'in millions' or 'in thousands')."
)
TOOLTIP_VALIDATION = (
    "Validation Check: Accounting verification (Passed, Alert, Failed Check, or Not Applicable) "
    "covering Balance Sheet balance (Assets = Liabilities + Equity), Segment Revenue totals, and "
    "year-over-year changes above ±30%. Any Failed Check stops for analyst review."
)
TOOLTIP_CHECKPOINT = (
    "Saved Audit Progress: FinovaLabs automatically saves completed work at every stage so closing "
    "your browser or restarting never loses decisions or repeats finished steps."
)

FIELD_TOOLTIPS: dict[str, str] = {
    "Confidence": TOOLTIP_CONFIDENCE,
    "Confidence Score": TOOLTIP_CONFIDENCE,
    "Evidence": TOOLTIP_EVIDENCE,
    "Citation": TOOLTIP_EVIDENCE,
    "10-K Quote": TOOLTIP_EVIDENCE,
    "Period": TOOLTIP_PERIOD,
    "Reporting Period": TOOLTIP_PERIOD,
    "Unit": TOOLTIP_UNIT,
    "Unit & Scale": TOOLTIP_UNIT,
    "Validation": TOOLTIP_VALIDATION,
    "Validation Status": TOOLTIP_VALIDATION,
    "Accounting Check": TOOLTIP_VALIDATION,
    "Rule": TOOLTIP_VALIDATION,
    "Last Checkpoint": TOOLTIP_CHECKPOINT,
    "Saved Step": TOOLTIP_CHECKPOINT,
    "Stage": TOOLTIP_CHECKPOINT,
}

_TOUR_SCREENS: tuple[dict[str, str], ...] = (
    {
        "title": "Overview",
        "url_path": "overview",
        "purpose": (
            "Your Audit Hub showing at a glance what is pending review, what is completed, any failed "
            "accounting checks, human analyst decisions, and saved work ready to continue."
        ),
        "action": (
            "Check the 'Recommended Next Step' box at the top, or click 'Continue' if an interrupted "
            "audit is waiting."
        ),
        "expect": (
            "A clear picture of portfolio audit progress and one direct button taking you to your next task."
        ),
    },
    {
        "title": "Filing Analysis",
        "url_path": "filing-analysis",
        "purpose": (
            "Lets you pick a supported public company (Apple, Microsoft, Alphabet, Amazon, or Walmart), "
            "download its official SEC Form 10-K, extract 8 core financial figures, and inspect proof & checks."
        ),
        "action": (
            "Follow Step 1 (Retrieve 10-K) then Step 2 (Extract 8 Core Financial Metrics) to gather "
            "figures and run accounting checks."
        ),
        "expect": (
            "Standardized USD and EPS figures with 10-K quotes, certainty ratings, and Balance Sheet / "
            "Segment / Year-over-Year check results."
        ),
    },
    {
        "title": "Human Review",
        "url_path": "human-review",
        "purpose": (
            "Brings every flagged item to the top whenever certainty is under 90%, a figure is missing, "
            "or an accounting check fails so an analyst can verify it against the filing."
        ),
        "action": (
            "Read the side-by-side 10-K quote, enter a short review note if correcting or rejecting, "
            "and click Approve, Correct Value, or Reject."
        ),
        "expect": (
            "Your decision is permanently recorded while preserving the original extracted figure, and "
            "the audit advances cleanly."
        ),
    },
    {
        "title": "Accuracy Report",
        "url_path": "accuracy-report",
        "purpose": (
            "Compares both the initial automated numbers and your final analyst-reviewed numbers against "
            "official SEC financial filings to verify reporting accuracy."
        ),
        "action": (
            "Select a company audit (or All Audit Runs) and click 'Evaluate vs. SEC Facts', then "
            "download your CSV or JSON summary report."
        ),
        "expect": (
            "Clear before-and-after accuracy percentages, company & metric charts, and downloadable reports."
        ),
    },
    {
        "title": "Audit Trail",
        "url_path": "audit-trail",
        "purpose": (
            "Provides a permanent, chronological Decision History of every analyst approval, edit, rejection, "
            "and audit milestone, protected by tamper-evident record linking."
        ),
        "action": (
            "Filter by Company, Date, Decision, or Metric, review Original vs. Corrected values, and verify "
            "or export the audit record."
        ),
        "expect": (
            "Confirmed record integrity with every analyst justification, timestamp, and before/after value intact."
        ),
    },
)


def reset_ui_session_state() -> None:
    """Safely reset browser UI/tour session preferences without deleting saved audit records."""
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


def _compact_html(raw: str) -> str:
    """Collapse HTML onto one space-joined line so CommonMark never emits code blocks or drops word spaces."""
    return " ".join(line.strip() for line in raw.splitlines() if line.strip())


def apply_design_system(
    active_section: str,
    db_status_label: str = "Audit Store Ready",
    context_summary: str | None = None,
) -> None:
    """Inject enterprise CSS, sidebar context, and persistent 'How to use FinovaLabs' help."""
    st.markdown(_ENTERPRISE_CSS, unsafe_allow_html=True)
    ctx_html = (
        _compact_html(
            f"""
            <div class="fl-sidebar-meta">
              <div class="fl-sidebar-meta-label">Active Audit Context</div>
              <div class="fl-sidebar-meta-value">{escape(context_summary)}</div>
            </div>
            """
        )
        if context_summary
        else ""
    )
    logo_svg = globals().get("_LOGO_SVG") or globals().get("LOGO_SVG") or _LOGO_SVG
    with st.sidebar:
        st.markdown(
            _compact_html(
                f"""
                <div class="fl-sidebar-brand">
                  <div style="width:36px;height:36px;flex-shrink:0;">{logo_svg}</div>
                  <div>
                    <div class="fl-wordmark"><span class="fl-wm-primary">FINOVA</span><span class="fl-wm-secondary">LABS</span></div>
                    <div class="fl-sidebar-brand-tag">SEC 10-K Research &amp; Audit</div>
                  </div>
                </div>
                {ctx_html}
                <div class="fl-sidebar-meta">
                  <div class="fl-sidebar-meta-label">Audit Record Store</div>
                  <div class="fl-sidebar-meta-value">{escape(db_status_label)}</div>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )
        with st.expander("How to use FinovaLabs", expanded=False):
            st.markdown(
                _compact_html(
                    """
                    <ol class="fl-sidebar-help-list">
                      <li><strong>Select company:</strong> Pick Apple, Microsoft, Alphabet, Amazon, or Walmart.</li>
                      <li><strong>Retrieve 10-K:</strong> Pull the official SEC annual filing &amp; financial facts.</li>
                      <li><strong>Extract metrics:</strong> Gather 8 key financial figures with exact 10-K quotes.</li>
                      <li><strong>Validate:</strong> Check certainty (&ge;90%), Balance Sheet, Segments &amp; YoY trends.</li>
                      <li><strong>Review exceptions:</strong> Sign off or fix flagged numbers in Human Review.</li>
                      <li><strong>Compare with SEC facts:</strong> Generate and download your Final SEC Report.</li>
                      <li><strong>View audit report:</strong> Inspect and verify full Decision History.</li>
                    </ol>
                    """
                ),
                unsafe_allow_html=True,
            )
            if st.button(
                "Start guided tour",
                key="sb_start_guided_tour",
                help="Walk through all 5 FinovaLabs screens step by step in plain English.",
                **stretch_width_kwargs(st.button),
            ):
                st.session_state["fl_tour_active"] = True
                st.session_state["fl_tour_step"] = 0
                st.rerun()

            if st.button(
                "Reset UI & Restart Tour",
                key="sb_safe_ui_reset",
                help="Clears only screen filters and tour progress. Saved filings and decisions stay untouched.",
                **stretch_width_kwargs(st.button),
            ):
                reset_ui_session_state()
                flash_feedback(
                    "info",
                    "Screen filters, welcome panel, and guided tour were reset safely. Saved filings and decisions remain intact.",
                )
                st.rerun()

            st.caption(
                "Safe Restart: Closing or refreshing your browser never deletes saved filings, decisions, or "
                "audit history. Unfinished audits resume safely from the Start & Audit Hub."
            )


def render_welcome_panel(
    *,
    allow_dismiss: bool = True,
    primary_label: str = "Start a new audit",
    primary_url: str = "filing-analysis",
) -> None:
    """Render the concise first-launch welcome banner with one primary action."""
    if st.session_state.get("fl_welcome_dismissed", False):
        return

    st.markdown(
        _compact_html(
            f"""
            <div class="fl-welcome-card">
              <div class="fl-welcome-title">Welcome to {escape(PRODUCT_NAME)} — Financial Audit Workspace</div>
              <p class="fl-welcome-body">
                Operational workspace for Form 10-K compliance audits: pull real SEC filings,
                extract 8 standardized financial figures with verbatim quotes, validate accounting equations,
                and resolve flagged review exceptions.
              </p>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    w1, w2, w3 = st.columns([1.6, 1.2, 0.9])
    with w1:
        navigate_button(
            primary_label,
            primary_url,
            key="welcome_go_fa",
            primary=True,
            help_text="Choose a company and retrieve its official SEC Form 10-K.",
        )
    with w2:
        if st.button(
            "Start guided tour",
            key="welcome_start_tour",
            type="secondary",
            help="Walk through the 5 audit workspace screens one step at a time.",
            **stretch_width_kwargs(st.button),
        ):
            st.session_state["fl_tour_active"] = True
            st.session_state["fl_tour_step"] = 0
            st.rerun()
    with w3:
        if allow_dismiss and st.button(
            "Dismiss welcome",
            key="welcome_dismiss_btn",
            help="Hide this welcome panel (you can reopen it anytime from 'How to use FinovaLabs' on the left).",
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
        _compact_html(
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
            """
        ),
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
        _compact_html(
            f"""
            <div class="fl-next-box">
              <strong>Next Action:</strong> {escape(next_action)}<br>
              <strong>Expected Result:</strong> {escape(expected_result)}
            </div>
            """
        ),
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
    failed_checks: int = 0,
    runs_count: int = 0,
    open_reviews: int = 0,
    resolved_reviews: int = 0,
    evaluations_count: int = 0,
    events_count: int = 0,
) -> None:
    """Render the persistent 7-stage end-to-end financial audit progress indicator."""
    steps = [
        (1, "1. Select company", f"{companies_count} company(s)" if companies_count else "Pick company", companies_count > 0),
        (2, "2. Retrieve 10-K", f"{filings_count} filing(s)" if filings_count else "Get SEC filing", filings_count > 0),
        (3, "3. Extract metrics", f"{metrics_count} figure(s)" if metrics_count else "8 core figures", metrics_count > 0),
        (
            4,
            "4. Validate",
            f"{failed_checks} failed check(s)"
            if failed_checks > 0
            else (f"{validations_count} check(s) ok" if validations_count else ("Checked" if runs_count else "Accounting rules")),
            (validations_count > 0 or runs_count > 0) and failed_checks == 0,
        ),
        (
            5,
            "5. Review exceptions",
            f"{open_reviews} pending"
            if open_reviews
            else (f"{resolved_reviews} signed off" if resolved_reviews else ("No exceptions" if runs_count else "Analyst sign-off")),
            runs_count > 0 and open_reviews == 0,
        ),
        (6, "6. Compare with SEC facts", f"{evaluations_count} verified" if evaluations_count else "Final report", evaluations_count > 0),
        (7, "7. View audit report", f"{events_count} record(s)" if events_count else "Decision history", events_count > 0 and evaluations_count > 0),
    ]
    blocks = []
    for num, label, sub, is_done in steps:
        if num == active_step:
            cls = "fl-step fl-step-active"
        elif num == 4 and failed_checks > 0:
            cls = "fl-step fl-step-fail"
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


def render_work_status_strip(
    *,
    pending_count: int = 0,
    completed_count: int = 0,
    failed_count: int = 0,
    human_decisions_count: int = 0,
) -> None:
    """Render a persistent 4-pill bar separating Pending, Completed, Failed Checks, and Human Decisions."""
    p_cls = "fl-work-pill-pending" if pending_count > 0 else "fl-work-pill-muted"
    c_cls = "fl-work-pill-completed" if completed_count > 0 else "fl-work-pill-muted"
    f_cls = "fl-work-pill-failed" if failed_count > 0 else "fl-work-pill-muted"
    h_cls = "fl-work-pill-human" if human_decisions_count > 0 else "fl-work-pill-muted"

    st.markdown(
        _compact_html(
            f"""
            <div class="fl-work-strip">
              <div class="fl-work-pill {p_cls}"><span class="fl-work-label"><span class="fl-work-dot"></span>Pending Work</span><span>{pending_count}</span></div>
              <div class="fl-work-pill {c_cls}"><span class="fl-work-label"><span class="fl-work-dot"></span>Completed Audits</span><span>{completed_count}</span></div>
              <div class="fl-work-pill {f_cls}"><span class="fl-work-label"><span class="fl-work-dot"></span>Failed Checks</span><span>{failed_count}</span></div>
              <div class="fl-work-pill {h_cls}"><span class="fl-work-label"><span class="fl-work-dot"></span>Human Decisions</span><span>{human_decisions_count}</span></div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def render_analyst_glossary_strip(*, expanded: bool = False) -> None:
    """Render plain-English contextual explanations for Confidence, Evidence, Period, Units, and Validation."""
    with st.expander("How to read audit fields (Confidence, Evidence, Period, Units & Validation)", expanded=expanded):
        st.markdown(
            _compact_html(
                f"""
                <div class="fl-glossary-grid">
                  <div class="fl-glossary-item"><strong>Confidence Score</strong>{escape(TOOLTIP_CONFIDENCE)}</div>
                  <div class="fl-glossary-item"><strong>Evidence &amp; 10-K Quote</strong>{escape(TOOLTIP_EVIDENCE)}</div>
                  <div class="fl-glossary-item"><strong>Reporting Period</strong>{escape(TOOLTIP_PERIOD)}</div>
                  <div class="fl-glossary-item"><strong>Units &amp; Scale</strong>{escape(TOOLTIP_UNIT)}</div>
                  <div class="fl-glossary-item"><strong>Validation Check</strong>{escape(TOOLTIP_VALIDATION)}</div>
                </div>
                """
            ),
            unsafe_allow_html=True,
        )


def render_page_header(
    title: str,
    subtitle: str,
    status_label: str = "Ready",
    status_tone: str = "info",
) -> None:
    """Render the branded enterprise header banner for a FinovaLabs page."""
    badge_html = status_badge(status_label, tone=status_tone)
    mark_svg = globals().get("_MARK_MINI_SVG") or globals().get("MARK_MINI_SVG") or _MARK_MINI_SVG
    st.markdown(
        _compact_html(
            f"""
            <div class="fl-header">
              <div>
                <div class="fl-header-eyebrow">{mark_svg}<span><strong>FINOVA</strong>LABS &bull; SEC 10-K RESEARCH &amp; AUDIT</span></div>
                <h1 class="fl-header-title">{escape(title)}</h1>
                <p class="fl-header-subtitle">{escape(subtitle)}</p>
              </div>
              <div>{badge_html}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def render_metric_cards(cards: Sequence[dict[str, str]]) -> None:
    """Render a responsive grid of KPI/configuration cards."""
    items_html = []
    for card in cards:
        items_html.append(
            _compact_html(
                f"""
                <div class="fl-card">
                  <div class="fl-kpi-label">{escape(card.get("label", ""))}</div>
                  <div class="fl-kpi-value">{escape(card.get("value", ""))}</div>
                  <div class="fl-kpi-detail">{escape(card.get("detail", ""))}</div>
                </div>
                """
            )
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
        _compact_html(
            f"""
            <div class="fl-card fl-info-card">
              <div class="fl-card-header">
                <h3 class="fl-card-title">{escape(title)}</h3>
                {badge_html}
              </div>
              <p class="fl-card-body">{escape(body)}</p>
            </div>
            """
        ),
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
        _compact_html(
            f"""
            <div class="fl-empty">
              <div class="fl-empty-badge">{escape(badge_label)}</div>
              <h3 class="fl-empty-title">{escape(title)}</h3>
              <p class="fl-empty-desc">{escape(description)}</p>
              {next_html}
            </div>
            """
        ),
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
        _compact_html(
            f"""
            <div class="fl-error-box">
              <div class="fl-error-title">{escape(title)}</div>
              <div>{escape(message)}</div>
              {hint_html}
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def render_status_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[tuple[str, str] | str]],
    right_align_cols: set[int] | None = None,
    header_tooltips: dict[str, str] | None = None,
    min_width: str | None = None,
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

    table_style = f' style="min-width: {min_width};"' if min_width else ""
    st.markdown(
        _compact_html(
            f"""
            <div class="fl-table-wrap">
              <table class="fl-table"{table_style}>
                <thead><tr>{head_html}</tr></thead>
                <tbody>{"".join(body_rows)}</tbody>
              </table>
            </div>
            """
        ),
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
    height: int = 380,
    legend_position: str = "bottom",
) -> None:
    """Style and render an interactive Plotly chart inside a crisp white editorial frame.

    Renders chart title as a clean editorial card header above the plot to eliminate
    any SVG canvas overlap with legends, plotting areas, and axis labels.
    """
    margin_b = 68 if legend_position == "bottom" else 36
    legend_kwargs: dict[str, Any]
    if legend_position == "bottom":
        legend_kwargs = dict(
            orientation="h",
            yanchor="top",
            y=-0.20,
            xanchor="center",
            x=0.5,
            font=dict(size=11, color="#273447"),
        )
    else:
        legend_kwargs = dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0.0,
            font=dict(size=11, color="#273447"),
        )

    fig.update_layout(
        title=None,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#273447", family="IBM Plex Sans, Inter, Segoe UI, sans-serif", size=11),
        margin=dict(l=16, r=16, t=20, b=margin_b),
        height=height,
        autosize=True,
        legend=legend_kwargs,
        hoverlabel=dict(bgcolor="#0C1B2E", font_color="#FFFFFF", bordercolor="#1E4B9A"),
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor="#DDDAD2",
        tickfont=dict(color="#273447", size=11),
        title_font=dict(color="#0C1B2E", size=11),
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor="#EFECE5",
        zerolinecolor="#DDDAD2",
        tickfont=dict(color="#273447", size=11),
        title_font=dict(color="#0C1B2E", size=11),
        automargin=True,
    )
    with st.container(border=True):
        if title:
            st.markdown(
                _compact_html(
                    f"""
                    <div class="fl-chart-header">
                      <div class="fl-chart-title">{escape(title)}</div>
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )
        st.plotly_chart(
            fig,
            key=key,
            theme=None,
            config={"displayModeBar": False, "responsive": True},
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
        _compact_html(
            f"""
            <div class="fl-footer">
              <span><strong>{escape(PRODUCT_NAME)}</strong> &mdash; {escape(PRODUCT_TAGLINE)}</span>
              <span>{escape(note)}</span>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
