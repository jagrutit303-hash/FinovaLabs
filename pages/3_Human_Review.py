"""Preserved standalone Human Review page delegating to FinovaLabs Human Review view."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from finova_labs.database import init_db
from finova_labs.ui import configure_page
from finova_labs.views import render_human_review_page

if __name__ == "__main__":
    configure_page("Human Review")
    init_db()
    render_human_review_page()
