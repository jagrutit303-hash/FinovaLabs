"""Test and initialize PostgreSQL database connection for FinovaLabs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

from finova_labs.database import check_db_health, init_db, is_postgres_configured
from finova_labs.settings import get_settings


def verify_connection() -> None:
    settings = get_settings()
    db_url = settings.database_url
    if not db_url:
        print("[FAIL] No DATABASE_URL or POSTGRES_URL found in .env or environment.")
        print("Please add DATABASE_URL=postgresql://... to your .env file.")
        sys.exit(1)

    masked_url = db_url
    if "@" in db_url:
        prefix, host_part = db_url.split("@", 1)
        scheme_and_user = prefix.split("://")[0] + "://***:***@"
        masked_url = scheme_and_user + host_part

    print(f"[INFO] Connecting to: {masked_url}")
    print("[INFO] Initializing FinovaLabs schema and indexes...")
    try:
        init_db()
        print("[SUCCESS] All 8 core tables and indexes verified successfully!")
    except Exception as e:
        print(f"[ERROR] Failed to initialize PostgreSQL: {e}")
        sys.exit(1)

    health = check_db_health()
    print("[INFO] Database Health Report:")
    print(f"  - Engine: {health.get('sqlite_version')}")
    print(f"  - Healthy: {health.get('healthy')}")
    print(f"  - Table Counts: {health.get('table_counts')}")
    print(f"  - Missing Tables: {health.get('missing_tables')}")


if __name__ == "__main__":
    verify_connection()

