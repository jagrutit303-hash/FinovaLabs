"""Streamlit entry point and multipage router for FinovaLabs."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st

from finova_labs.database import init_db
from finova_labs.logging_config import configure_logging, get_logger
from finova_labs.settings import get_settings
from finova_labs.ui import configure_page, safe_execute
from finova_labs.views import (
    render_accuracy_report_page,
    render_audit_trail_page,
    render_filing_analysis_page,
    render_human_review_page,
    render_overview_page,
)


@st.cache_resource
def _initialize_foundation() -> bool:
    """Initialize settings, rotating logs, and SQLite schema once per server process."""
    settings = get_settings()
    configure_logging(settings)
    init_db(settings.db_file)
    get_logger("app").info("FinovaLabs foundation initialized (db=%s)", settings.db_file)
    return True


def main() -> None:
    """Configure FinovaLabs page shell, initialize foundation, and route navigation."""
    configure_page()
    safe_execute(_initialize_foundation, "application startup")

    page_specs = [
        ("overview", render_overview_page, "Overview", ":material/space_dashboard:", True),
        ("filing-analysis", render_filing_analysis_page, "Filing Analysis", ":material/analytics:", False),
        ("human-review", render_human_review_page, "Human Review", ":material/fact_check:", False),
        ("accuracy-report", render_accuracy_report_page, "Accuracy Report", ":material/verified:", False),
        ("audit-trail", render_audit_trail_page, "Audit Trail", ":material/receipt_long:", False),
    ]
    pages = [
        st.Page(fn, title=title, icon=icon, url_path=url_path, default=is_default)
        for url_path, fn, title, icon, is_default in page_specs
    ]
    st.session_state["fl_pages"] = {
        url_path: page_obj
        for (url_path, _, _, _, _), page_obj in zip(page_specs, pages)
    }

    navigation = st.navigation(pages, position="sidebar", expanded=True)
    navigation.run()


if __name__ == "__main__":
    main()
