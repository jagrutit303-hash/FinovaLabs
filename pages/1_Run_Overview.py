"""Preserved standalone Run Overview page delegating to FinovaLabs Overview view."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from finova_labs.database import init_db
from finova_labs.ui import configure_page
from finova_labs.views import render_overview_page

if __name__ == "__main__":
    configure_page("Overview")
    init_db()
    render_overview_page()
