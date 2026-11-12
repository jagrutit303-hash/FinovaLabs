"""Preserved standalone Metrics & Evidence page delegating to Filing Analysis view."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from finova_labs.database import init_db
from finova_labs.ui import configure_page
from finova_labs.views import render_filing_analysis_page

if __name__ == "__main__":
    configure_page("Filing Analysis")
    init_db()
    render_filing_analysis_page()
