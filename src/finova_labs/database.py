"""SQLite database schema, connection management, and foundation queries."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from finova_labs.exceptions import DatabaseError
from finova_labs.logging_config import get_logger
from finova_labs.settings import get_settings

logger = get_logger("database")

CORE_TABLES: tuple[str, ...] = (
    "audit_runs",
    "sec_filings",
    "extracted_metrics",
    "review_tasks",
    "validation_results",
    "accuracy_evaluations",
    "audit_events",
    "idempotency_records",
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_runs (
    run_id TEXT PRIMARY KEY,
    cik TEXT NOT NULL,
    filing_id INTEGER,
    accession_number TEXT,
    idempotency_key TEXT,
    company_name TEXT,
    ticker TEXT,
    form_type TEXT NOT NULL,
    fiscal_year INTEGER,
    status TEXT NOT NULL DEFAULT 'PENDING',
    current_stage TEXT NOT NULL DEFAULT 'PENDING',
    overall_confidence REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS sec_filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik TEXT NOT NULL,
    ticker TEXT,
    company_name TEXT,
    accession_number TEXT NOT NULL,
    form_type TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    reporting_period TEXT,
    fiscal_year INTEGER,
    retrieval_status TEXT NOT NULL DEFAULT 'RETRIEVED',
    primary_document TEXT,
    filing_url TEXT NOT NULL,
    submissions_url TEXT NOT NULL,
    companyfacts_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(cik, accession_number)
);

CREATE TABLE IF NOT EXISTS extracted_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    cik TEXT,
    ticker TEXT,
    accession_number TEXT,
    form_type TEXT,
    metric_name TEXT NOT NULL,
    xbrl_concept TEXT,
    raw_value TEXT,
    normalized_value REAL,
    normalized_decimal TEXT,
    unit TEXT DEFAULT 'USD',
    currency TEXT DEFAULT 'USD',
    scale_factor INTEGER DEFAULT 1,
    fiscal_period TEXT,
    fiscal_year INTEGER,
    period_start TEXT,
    period_end TEXT,
    source_url TEXT,
    source_evidence TEXT,
    evidence_location TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'EXTRACTED',
    candidates_json TEXT,
    confidence_score REAL,
    confidence_components_json TEXT,
    confidence_reasons TEXT,
    confidence_threshold REAL,
    scoring_version TEXT,
    validation_status TEXT NOT NULL DEFAULT 'PENDING',
    review_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
    reviewed_value REAL,
    reviewed_decimal TEXT,
    reviewer_note TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT,
    cik TEXT,
    ticker TEXT,
    accession_number TEXT,
    metric_id INTEGER,
    metric_name TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    reviewer_note TEXT,
    resolved_value REAL,
    resolved_decimal TEXT,
    resolved_by TEXT,
    decision_key TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES extracted_metrics(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS validation_results (
    validation_id TEXT PRIMARY KEY,
    run_id TEXT,
    cik TEXT NOT NULL,
    ticker TEXT,
    accession_number TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    status TEXT NOT NULL,
    explanation TEXT NOT NULL,
    input_metric_refs_json TEXT NOT NULL,
    expected_value TEXT,
    actual_value TEXT,
    variance_abs TEXT,
    variance_pct TEXT,
    tolerance_used TEXT,
    escalated INTEGER NOT NULL DEFAULT 0,
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS accuracy_evaluations (
    eval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    metric_id INTEGER,
    cik TEXT,
    ticker TEXT,
    company_name TEXT,
    accession_number TEXT,
    form_type TEXT,
    metric_name TEXT NOT NULL,
    xbrl_concept TEXT,
    unit TEXT,
    fiscal_period TEXT,
    fiscal_year INTEGER,
    period_start TEXT,
    period_end TEXT,
    extracted_value REAL,
    pre_review_decimal TEXT,
    post_review_decimal TEXT,
    review_status TEXT,
    ground_truth_value REAL,
    ground_truth_decimal TEXT,
    ground_truth_unit TEXT,
    ground_truth_concept TEXT,
    ground_truth_fiscal_period TEXT,
    ground_truth_period_start TEXT,
    ground_truth_period_end TEXT,
    ground_truth_accession TEXT,
    abs_diff REAL,
    rel_diff REAL,
    matched INTEGER NOT NULL DEFAULT 0,
    pre_abs_diff TEXT,
    pre_pct_diff TEXT,
    pre_exact_match INTEGER NOT NULL DEFAULT 0,
    pre_status TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE',
    post_abs_diff TEXT,
    post_pct_diff TEXT,
    post_exact_match INTEGER NOT NULL DEFAULT 0,
    post_status TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE',
    comparison_status TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE',
    explanation TEXT,
    reference_source_url TEXT,
    reference_fact_json TEXT,
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seq_id INTEGER,
    run_id TEXT,
    cik TEXT,
    ticker TEXT,
    company_name TEXT,
    filing_id INTEGER,
    accession_number TEXT,
    metric_id INTEGER,
    metric_name TEXT,
    event_type TEXT NOT NULL,
    decision TEXT,
    original_value TEXT,
    corrected_value TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    reviewer_id TEXT,
    session_id TEXT,
    explanation TEXT,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    hash_version INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    target_id TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sec_filings_cik_form ON sec_filings(cik, form_type, filing_date);
CREATE INDEX IF NOT EXISTS idx_extracted_metrics_run_id ON extracted_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_review_tasks_status ON review_tasks(status);
CREATE INDEX IF NOT EXISTS idx_accuracy_eval_run_id ON accuracy_evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_run_id ON audit_events(run_id);
"""

_SCHEMA_SQL_PG = """
CREATE TABLE IF NOT EXISTS audit_runs (
    run_id TEXT PRIMARY KEY,
    cik TEXT NOT NULL,
    filing_id INTEGER,
    accession_number TEXT,
    idempotency_key TEXT,
    company_name TEXT,
    ticker TEXT,
    form_type TEXT NOT NULL,
    fiscal_year INTEGER,
    status TEXT NOT NULL DEFAULT 'PENDING',
    current_stage TEXT NOT NULL DEFAULT 'PENDING',
    overall_confidence DOUBLE PRECISION,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS sec_filings (
    id SERIAL PRIMARY KEY,
    cik TEXT NOT NULL,
    ticker TEXT,
    company_name TEXT,
    accession_number TEXT NOT NULL,
    form_type TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    reporting_period TEXT,
    fiscal_year INTEGER,
    retrieval_status TEXT NOT NULL DEFAULT 'RETRIEVED',
    primary_document TEXT,
    filing_url TEXT NOT NULL,
    submissions_url TEXT NOT NULL,
    companyfacts_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(cik, accession_number)
);

CREATE TABLE IF NOT EXISTS extracted_metrics (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    cik TEXT,
    ticker TEXT,
    accession_number TEXT,
    form_type TEXT,
    metric_name TEXT NOT NULL,
    xbrl_concept TEXT,
    raw_value TEXT,
    normalized_value DOUBLE PRECISION,
    normalized_decimal TEXT,
    unit TEXT DEFAULT 'USD',
    currency TEXT DEFAULT 'USD',
    scale_factor INTEGER DEFAULT 1,
    fiscal_period TEXT,
    fiscal_year INTEGER,
    period_start TEXT,
    period_end TEXT,
    source_url TEXT,
    source_evidence TEXT,
    evidence_location TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'EXTRACTED',
    candidates_json TEXT,
    confidence_score DOUBLE PRECISION,
    confidence_components_json TEXT,
    confidence_reasons TEXT,
    confidence_threshold DOUBLE PRECISION,
    scoring_version TEXT,
    validation_status TEXT NOT NULL DEFAULT 'PENDING',
    review_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
    reviewed_value DOUBLE PRECISION,
    reviewed_decimal TEXT,
    reviewer_note TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT,
    cik TEXT,
    ticker TEXT,
    accession_number TEXT,
    metric_id INTEGER,
    metric_name TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    reviewer_note TEXT,
    resolved_value DOUBLE PRECISION,
    resolved_decimal TEXT,
    resolved_by TEXT,
    decision_key TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (metric_id) REFERENCES extracted_metrics(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS validation_results (
    validation_id TEXT PRIMARY KEY,
    run_id TEXT,
    cik TEXT NOT NULL,
    ticker TEXT,
    accession_number TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    status TEXT NOT NULL,
    explanation TEXT NOT NULL,
    input_metric_refs_json TEXT NOT NULL,
    expected_value TEXT,
    actual_value TEXT,
    variance_abs TEXT,
    variance_pct TEXT,
    tolerance_used TEXT,
    escalated INTEGER NOT NULL DEFAULT 0,
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS accuracy_evaluations (
    eval_id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    metric_id INTEGER,
    cik TEXT,
    ticker TEXT,
    company_name TEXT,
    accession_number TEXT,
    form_type TEXT,
    metric_name TEXT NOT NULL,
    xbrl_concept TEXT,
    unit TEXT,
    fiscal_period TEXT,
    fiscal_year INTEGER,
    period_start TEXT,
    period_end TEXT,
    extracted_value DOUBLE PRECISION,
    pre_review_decimal TEXT,
    post_review_decimal TEXT,
    review_status TEXT,
    ground_truth_value DOUBLE PRECISION,
    ground_truth_decimal TEXT,
    ground_truth_unit TEXT,
    ground_truth_concept TEXT,
    ground_truth_fiscal_period TEXT,
    ground_truth_period_start TEXT,
    ground_truth_period_end TEXT,
    ground_truth_accession TEXT,
    abs_diff DOUBLE PRECISION,
    rel_diff DOUBLE PRECISION,
    matched INTEGER NOT NULL DEFAULT 0,
    pre_abs_diff TEXT,
    pre_pct_diff TEXT,
    pre_exact_match INTEGER NOT NULL DEFAULT 0,
    pre_status TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE',
    post_abs_diff TEXT,
    post_pct_diff TEXT,
    post_exact_match INTEGER NOT NULL DEFAULT 0,
    post_status TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE',
    comparison_status TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE',
    explanation TEXT,
    reference_source_url TEXT,
    reference_fact_json TEXT,
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id SERIAL PRIMARY KEY,
    seq_id INTEGER,
    run_id TEXT,
    cik TEXT,
    ticker TEXT,
    company_name TEXT,
    filing_id INTEGER,
    accession_number TEXT,
    metric_id INTEGER,
    metric_name TEXT,
    event_type TEXT NOT NULL,
    decision TEXT,
    original_value TEXT,
    corrected_value TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    reviewer_id TEXT,
    session_id TEXT,
    explanation TEXT,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    hash_version INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    target_id TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sec_filings_cik_form ON sec_filings(cik, form_type, filing_date);
CREATE INDEX IF NOT EXISTS idx_extracted_metrics_run_id ON extracted_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_review_tasks_status ON review_tasks(status);
CREATE INDEX IF NOT EXISTS idx_accuracy_eval_run_id ON accuracy_evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_run_id ON audit_events(run_id);
"""


class SmartRow(dict):
    """Dictionary subclass providing both key-based and integer-index access (sqlite3.Row parity)."""

    def __init__(self, d: dict[str, Any], keys: list[str]) -> None:
        super().__init__(d)
        self._keys = list(keys)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, int):
            return super().__getitem__(self._keys[item])
        return super().__getitem__(item)


def _smart_row_factory(cursor: Any) -> Any:
    names = [c.name for c in cursor.description] if cursor.description else []

    def make_row(values: Any) -> SmartRow:
        return SmartRow(dict(zip(names, values)), names)

    return make_row


class PgCursorWrapper:
    """Adapts a psycopg cursor to sqlite3 parameter syntax ('?' -> '%s') and SmartRow objects."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    @staticmethod
    def _adapt_query(query: str) -> str:
        q_strip = query.strip()
        if q_strip.upper().startswith("PRAGMA"):
            return "SELECT 1;"
        parts = query.split("'")
        for i in range(0, len(parts), 2):
            parts[i] = parts[i].replace("?", "%s")
        return "'".join(parts)

    def execute(self, query: str, params: Any = None) -> PgCursorWrapper:
        adapted = self._adapt_query(query)
        if params is not None:
            self._cursor.execute(adapted, params)
        else:
            self._cursor.execute(adapted)
        return self

    def executemany(self, query: str, seq_of_params: Any) -> PgCursorWrapper:
        adapted = self._adapt_query(query)
        self._cursor.executemany(adapted, seq_of_params)
        return self

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()

    def __iter__(self) -> Iterator[Any]:
        return iter(self._cursor)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


class PgConnectionWrapper:
    """Wraps a psycopg Connection to provide a sqlite3-compatible interface with autocommit/rollback."""

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn

    def execute(self, query: str, params: Any = None) -> PgCursorWrapper:
        cursor = self._conn.cursor(row_factory=_smart_row_factory)
        wrapper = PgCursorWrapper(cursor)
        wrapper.execute(query, params)
        return wrapper

    def executemany(self, query: str, seq_of_params: Any) -> PgCursorWrapper:
        cursor = self._conn.cursor(row_factory=_smart_row_factory)
        wrapper = PgCursorWrapper(cursor)
        wrapper.executemany(query, seq_of_params)
        return wrapper

    def executescript(self, script: str) -> None:
        for stmt in script.split(";"):
            clean = stmt.strip()
            if clean:
                self.execute(clean)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def is_postgres_configured() -> bool:
    """Return True if DATABASE_URL or POSTGRES_URL is configured for PostgreSQL."""
    try:
        url = get_settings().database_url
        if url and (url.startswith("postgresql://") or url.startswith("postgres://")):
            return True
    except Exception:
        pass
    return False


def resolve_db_path(db_path: Path | str | None = None) -> Path:
    """Resolve target SQLite database path from argument or centralized settings."""
    if db_path is not None:
        return Path(db_path).resolve()
    return get_settings().db_file


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Iterator[Any]:
    """Yield a managed database connection (PostgreSQL when configured, otherwise SQLite WAL)."""
    if is_postgres_configured():
        import psycopg
        db_url = get_settings().database_url
        raw_conn = None
        wrapper = None
        try:
            raw_conn = psycopg.connect(db_url)
            wrapper = PgConnectionWrapper(raw_conn)
            yield wrapper
            wrapper.commit()
        except Exception as exc:
            if wrapper is not None:
                wrapper.rollback()
            logger.exception("PostgreSQL database transaction failed")
            raise DatabaseError(f"PostgreSQL operation failed: {exc}") from exc
        finally:
            if wrapper is not None:
                wrapper.close()
        return

    target = resolve_db_path(db_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.Error as exc:
        logger.exception("Failed to open SQLite database at %s", target)
        raise DatabaseError(
            f"Unable to connect to SQLite database at {target}",
            hint="Verify directory permissions and ensure the file is not locked.",
        ) from exc
    except OSError as exc:
        logger.exception("Filesystem error preparing database directory for %s", target)
        raise DatabaseError(
            f"Unable to prepare database directory for {target}: {exc}",
            hint="Check disk space and write permissions in the workspace.",
        ) from exc

    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.exception("SQLite transaction failed on %s", target)
        raise DatabaseError(
            f"Database operation failed: {exc}",
            hint="Check application logs for query details.",
        ) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def _migrate_sec_filings(conn: sqlite3.Connection) -> None:
    """Add new metadata columns to existing sec_filings tables without data loss."""
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sec_filings)").fetchall()
    }
    if "fiscal_year" not in columns:
        conn.execute("ALTER TABLE sec_filings ADD COLUMN fiscal_year INTEGER")
    if "retrieval_status" not in columns:
        conn.execute(
            "ALTER TABLE sec_filings ADD COLUMN retrieval_status TEXT NOT NULL DEFAULT 'RETRIEVED'"
        )


def _migrate_extracted_metrics(conn: sqlite3.Connection) -> None:
    """Ensure extracted_metrics supports nullable run_id and full provenance columns."""
    info = conn.execute("PRAGMA table_info(extracted_metrics)").fetchall()
    col_map = {row["name"]: row for row in info}

    # If created by earlier foundation with NOT NULL run_id and missing provenance columns,
    # migrate safely while preserving any existing rows.
    run_id_notnull = col_map.get("run_id") and col_map["run_id"]["notnull"] == 1
    if run_id_notnull:
        existing_rows = conn.execute(
            """
            SELECT id, run_id, metric_name, xbrl_concept, raw_value, normalized_value,
                   unit, period_start, period_end, confidence_score,
                   validation_status, review_status, source_evidence, created_at
            FROM extracted_metrics
            """
        ).fetchall()
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("DROP TABLE extracted_metrics;")
        conn.execute(
            """
            CREATE TABLE extracted_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                cik TEXT,
                ticker TEXT,
                accession_number TEXT,
                form_type TEXT,
                metric_name TEXT NOT NULL,
                xbrl_concept TEXT,
                raw_value TEXT,
                normalized_value REAL,
                normalized_decimal TEXT,
                unit TEXT DEFAULT 'USD',
                currency TEXT DEFAULT 'USD',
                scale_factor INTEGER DEFAULT 1,
                fiscal_period TEXT,
                fiscal_year INTEGER,
                period_start TEXT,
                period_end TEXT,
                source_url TEXT,
                source_evidence TEXT,
                evidence_location TEXT,
                extraction_status TEXT NOT NULL DEFAULT 'EXTRACTED',
                candidates_json TEXT,
                confidence_score REAL,
                confidence_components_json TEXT,
                confidence_reasons TEXT,
                confidence_threshold REAL,
                scoring_version TEXT,
                validation_status TEXT NOT NULL DEFAULT 'PENDING',
                review_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
                reviewed_value REAL,
                reviewed_decimal TEXT,
                reviewer_note TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE
            );
            """
        )
        for row in existing_rows:
            conn.execute(
                """
                INSERT INTO extracted_metrics (
                    id, run_id, metric_name, xbrl_concept, raw_value, normalized_value,
                    unit, period_start, period_end, confidence_score,
                    validation_status, review_status, source_evidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row),
            )
        conn.execute("PRAGMA foreign_keys = ON;")
        return

    extra_cols = {
        "cik": "TEXT",
        "ticker": "TEXT",
        "accession_number": "TEXT",
        "form_type": "TEXT",
        "normalized_decimal": "TEXT",
        "currency": "TEXT DEFAULT 'USD'",
        "scale_factor": "INTEGER DEFAULT 1",
        "fiscal_period": "TEXT",
        "fiscal_year": "INTEGER",
        "source_url": "TEXT",
        "evidence_location": "TEXT",
        "extraction_status": "TEXT NOT NULL DEFAULT 'EXTRACTED'",
        "candidates_json": "TEXT",
        "confidence_components_json": "TEXT",
        "confidence_reasons": "TEXT",
        "confidence_threshold": "REAL",
        "scoring_version": "TEXT",
        "reviewed_value": "REAL",
        "reviewed_decimal": "TEXT",
        "reviewer_note": "TEXT",
        "reviewed_by": "TEXT",
        "reviewed_at": "TEXT",
    }
    for col_name, col_type in extra_cols.items():
        if col_name not in col_map:
            conn.execute(f"ALTER TABLE extracted_metrics ADD COLUMN {col_name} {col_type}")


def _migrate_review_tasks(conn: sqlite3.Connection) -> None:
    """Make review_tasks.run_id nullable and add filing/metric traceability columns."""
    cols = conn.execute("PRAGMA table_info(review_tasks);").fetchall()
    if not cols:
        return

    col_map = {row["name"]: row for row in cols}
    run_id_not_null = col_map.get("run_id") is not None and col_map["run_id"]["notnull"] == 1
    if run_id_not_null:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute(
            """
            CREATE TABLE review_tasks_new (
                task_id TEXT PRIMARY KEY,
                run_id TEXT,
                cik TEXT,
                ticker TEXT,
                accession_number TEXT,
                metric_id INTEGER,
                metric_name TEXT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                reviewer_note TEXT,
                resolved_value REAL,
                resolved_decimal TEXT,
                resolved_by TEXT,
                decision_key TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (run_id) REFERENCES audit_runs(run_id) ON DELETE CASCADE,
                FOREIGN KEY (metric_id) REFERENCES extracted_metrics(id) ON DELETE SET NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO review_tasks_new (
                task_id, run_id, metric_id, reason, status,
                reviewer_note, resolved_value, resolved_by, created_at, resolved_at
            )
            SELECT task_id, run_id, metric_id, reason, status,
                   reviewer_note, resolved_value, resolved_by, created_at, resolved_at
            FROM review_tasks;
            """
        )
        conn.execute("DROP TABLE review_tasks;")
        conn.execute("ALTER TABLE review_tasks_new RENAME TO review_tasks;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return

    extra_cols = {
        "cik": "TEXT",
        "ticker": "TEXT",
        "accession_number": "TEXT",
        "metric_name": "TEXT",
        "resolved_decimal": "TEXT",
        "decision_key": "TEXT",
    }
    for col_name, col_type in extra_cols.items():
        if col_name not in col_map:
            conn.execute(f"ALTER TABLE review_tasks ADD COLUMN {col_name} {col_type}")


def _migrate_audit_runs(conn: sqlite3.Connection) -> None:
    """Add filing linkage, idempotency_key, and stage tracking columns to existing audit_runs."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(audit_runs);").fetchall()}
    extra_cols = {
        "filing_id": "INTEGER",
        "accession_number": "TEXT",
        "idempotency_key": "TEXT",
        "current_stage": "TEXT NOT NULL DEFAULT 'PENDING'",
    }
    for col_name, col_type in extra_cols.items():
        if col_name not in cols:
            conn.execute(f"ALTER TABLE audit_runs ADD COLUMN {col_name} {col_type}")


def _migrate_accuracy_evaluations(conn: sqlite3.Connection) -> None:
    """Add provenance, unit/period verification, and pre/post review columns to accuracy_evaluations."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(accuracy_evaluations);").fetchall()}
    extra_cols = {
        "metric_id": "INTEGER",
        "cik": "TEXT",
        "ticker": "TEXT",
        "company_name": "TEXT",
        "accession_number": "TEXT",
        "form_type": "TEXT",
        "xbrl_concept": "TEXT",
        "unit": "TEXT",
        "fiscal_period": "TEXT",
        "fiscal_year": "INTEGER",
        "period_start": "TEXT",
        "period_end": "TEXT",
        "pre_review_decimal": "TEXT",
        "post_review_decimal": "TEXT",
        "review_status": "TEXT",
        "ground_truth_decimal": "TEXT",
        "ground_truth_unit": "TEXT",
        "ground_truth_concept": "TEXT",
        "ground_truth_fiscal_period": "TEXT",
        "ground_truth_period_start": "TEXT",
        "ground_truth_period_end": "TEXT",
        "ground_truth_accession": "TEXT",
        "pre_abs_diff": "TEXT",
        "pre_pct_diff": "TEXT",
        "pre_exact_match": "INTEGER NOT NULL DEFAULT 0",
        "pre_status": "TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE'",
        "post_abs_diff": "TEXT",
        "post_pct_diff": "TEXT",
        "post_exact_match": "INTEGER NOT NULL DEFAULT 0",
        "post_status": "TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE'",
        "comparison_status": "TEXT NOT NULL DEFAULT 'UNAVAILABLE_REFERENCE'",
        "explanation": "TEXT",
        "reference_source_url": "TEXT",
        "reference_fact_json": "TEXT",
    }
    for col_name, col_type in extra_cols.items():
        if col_name not in cols:
            conn.execute(f"ALTER TABLE accuracy_evaluations ADD COLUMN {col_name} {col_type}")


def _migrate_audit_events(conn: sqlite3.Connection) -> None:
    """Add structured audit metadata and seq_id columns to legacy audit_events without breaking v1 hashes."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(audit_events);").fetchall()}
    if not cols:
        return
    is_legacy = "hash_version" not in cols
    if is_legacy:
        conn.execute("ALTER TABLE audit_events ADD COLUMN hash_version INTEGER NOT NULL DEFAULT 1")
    extra_cols = {
        "seq_id": "INTEGER",
        "cik": "TEXT",
        "ticker": "TEXT",
        "company_name": "TEXT",
        "filing_id": "INTEGER",
        "accession_number": "TEXT",
        "metric_id": "INTEGER",
        "metric_name": "TEXT",
        "decision": "TEXT",
        "original_value": "TEXT",
        "corrected_value": "TEXT",
        "reviewer_id": "TEXT",
        "session_id": "TEXT",
        "explanation": "TEXT",
    }
    for col_name, col_type in extra_cols.items():
        if col_name not in cols:
            conn.execute(f"ALTER TABLE audit_events ADD COLUMN {col_name} {col_type}")

    # Backfill monotonic seq_id ONLY when rows have missing seq_id and are being upgraded
    if is_legacy:
        rows = conn.execute("SELECT event_id FROM audit_events ORDER BY event_id ASC").fetchall()
        for seq_num, row in enumerate(rows, start=1):
            conn.execute(
                "UPDATE audit_events SET seq_id = ? WHERE event_id = ? AND seq_id IS NULL",
                (seq_num, row["event_id"]),
            )


def init_db(db_path: Path | str | None = None) -> Any:
    """Create FinovaLabs tables and indexes in PostgreSQL or SQLite if they do not already exist."""
    if is_postgres_configured():
        with get_connection() as conn:
            conn.executescript(_SCHEMA_SQL_PG)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_runs_idempotency_key "
                "ON audit_runs(idempotency_key) WHERE idempotency_key IS NOT NULL;"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_runs_status "
                "ON audit_runs(status, current_stage);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_extracted_metrics_accn "
                "ON extracted_metrics(cik, accession_number);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_tasks_accn "
                "ON review_tasks(cik, accession_number, status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_tasks_run_status "
                "ON review_tasks(run_id, status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_validation_results_accn "
                "ON validation_results(cik, accession_number, status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_accuracy_evaluations_run "
                "ON accuracy_evaluations(run_id, metric_name);"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_events_seq_id "
                "ON audit_events(seq_id) WHERE seq_id IS NOT NULL;"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_filters "
                "ON audit_events(ticker, cik, created_at, decision, metric_name);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_events_accn "
                "ON audit_events(accession_number);"
            )
        logger.info("PostgreSQL database initialized successfully")
        return Path("postgresql://active")

    target = resolve_db_path(db_path)
    with get_connection(target) as conn:
        conn.executescript(_SCHEMA_SQL)
        _migrate_audit_runs(conn)
        _migrate_sec_filings(conn)
        _migrate_extracted_metrics(conn)
        _migrate_review_tasks(conn)
        _migrate_accuracy_evaluations(conn)
        _migrate_audit_events(conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_runs_idempotency_key "
            "ON audit_runs(idempotency_key) WHERE idempotency_key IS NOT NULL;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_runs_status "
            "ON audit_runs(status, current_stage);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_extracted_metrics_accn "
            "ON extracted_metrics(cik, accession_number);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_tasks_accn "
            "ON review_tasks(cik, accession_number, status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_tasks_run_status "
            "ON review_tasks(run_id, status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_validation_results_accn "
            "ON validation_results(cik, accession_number, status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_accuracy_evaluations_run "
            "ON accuracy_evaluations(run_id, metric_name);"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_events_seq_id "
            "ON audit_events(seq_id) WHERE seq_id IS NOT NULL;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_events_filters "
            "ON audit_events(ticker, cik, created_at, decision, metric_name);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_events_accn "
            "ON audit_events(accession_number);"
        )
    logger.info("SQLite database initialized at %s", target)
    return target


@contextmanager
def _optional_transaction(
    conn: Any = None,
    db_path: Path | str | None = None,
) -> Iterator[Any]:
    """Yield an active transaction connection, or open/commit a new get_connection."""
    if conn is not None:
        yield conn
        return
    with get_connection(db_path) as new_conn:
        yield new_conn


def _query_all(
    sql: str,
    params: tuple[Any, ...] = (),
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Execute a read query and return rows as plain dictionaries."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def check_db_health(db_path: Path | str | None = None) -> dict[str, Any]:
    """Verify database connectivity, table presence, and current record counts."""
    if is_postgres_configured():
        with get_connection() as conn:
            ver_row = conn.execute("SELECT version()").fetchone()
            pg_version = ver_row[0] if ver_row else "PostgreSQL"
            existing_tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT table_name as name FROM information_schema.tables WHERE table_schema = 'public'"
                ).fetchall()
            }
            missing_tables = [t for t in CORE_TABLES if t not in existing_tables]
            table_counts = {
                table: (
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    if table in existing_tables
                    else 0
                )
                for table in CORE_TABLES
            }
        return {
            "db_path": "PostgreSQL (Managed Cloud Database)",
            "sqlite_version": f"PostgreSQL ({pg_version[:32]})",
            "size_bytes": 0,
            "healthy": len(missing_tables) == 0,
            "missing_tables": missing_tables,
            "table_counts": table_counts,
        }

    target = resolve_db_path(db_path)
    with get_connection(target) as conn:
        sqlite_version = conn.execute("SELECT sqlite_version()").fetchone()[0]
        existing_tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing_tables = [t for t in CORE_TABLES if t not in existing_tables]
        table_counts = {
            table: (
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if table in existing_tables
                else 0
            )
            for table in CORE_TABLES
        }

    size_bytes = target.stat().st_size if target.is_file() else 0
    return {
        "db_path": str(target),
        "sqlite_version": sqlite_version,
        "size_bytes": size_bytes,
        "healthy": len(missing_tables) == 0,
        "missing_tables": missing_tables,
        "table_counts": table_counts,
    }


def fetch_dashboard_summary(db_path: Path | str | None = None) -> dict[str, int]:
    """Fetch aggregate integer counts for the FinovaLabs Overview page."""
    with get_connection(db_path) as conn:
        total_companies = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT cik FROM sec_filings
                UNION
                SELECT cik FROM audit_runs
            )
            """
        ).fetchone()[0]
        retrieved_filings = conn.execute(
            "SELECT COUNT(*) FROM sec_filings WHERE retrieval_status = 'RETRIEVED'"
        ).fetchone()[0]
        total_runs = conn.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0]
        completed_runs = conn.execute(
            "SELECT COUNT(*) FROM audit_runs WHERE status IN ('COMPLETED', 'COMPLETED_WITH_REJECTIONS')"
        ).fetchone()[0]
        paused_runs = conn.execute(
            "SELECT COUNT(*) FROM audit_runs WHERE status = 'PAUSED_FOR_REVIEW'"
        ).fetchone()[0]
        interrupted_runs = conn.execute(
            "SELECT COUNT(*) FROM audit_runs WHERE status = 'INTERRUPTED'"
        ).fetchone()[0]
        extracted_metrics = conn.execute(
            "SELECT COUNT(*) FROM extracted_metrics"
        ).fetchone()[0]
        auto_approved_metrics = conn.execute(
            "SELECT COUNT(*) FROM extracted_metrics WHERE review_status = 'AUTO_APPROVED'"
        ).fetchone()[0]
        open_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_tasks WHERE status = 'OPEN'"
        ).fetchone()[0]
        total_escalations = conn.execute(
            "SELECT COUNT(*) FROM review_tasks"
        ).fetchone()[0]
        resolved_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_tasks WHERE status != 'OPEN'"
        ).fetchone()[0]
        evaluations = conn.execute(
            "SELECT COUNT(*) FROM accuracy_evaluations"
        ).fetchone()[0]
        evaluable_evaluations = conn.execute(
            "SELECT COUNT(*) FROM accuracy_evaluations WHERE ground_truth_decimal IS NOT NULL OR ground_truth_value IS NOT NULL"
        ).fetchone()[0]
        pre_exact_matches = conn.execute(
            "SELECT COUNT(*) FROM accuracy_evaluations WHERE pre_exact_match = 1"
        ).fetchone()[0]
        post_exact_matches = conn.execute(
            "SELECT COUNT(*) FROM accuracy_evaluations WHERE post_exact_match = 1"
        ).fetchone()[0]
        audit_events = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        validation_checks = conn.execute("SELECT COUNT(*) FROM validation_results").fetchone()[0]
        failed_validations = conn.execute(
            "SELECT COUNT(*) FROM validation_results WHERE status = 'FAIL'"
        ).fetchone()[0]
        warning_validations = conn.execute(
            "SELECT COUNT(*) FROM validation_results WHERE status = 'WARNING'"
        ).fetchone()[0]

    return {
        "total_companies": total_companies,
        "retrieved_filings": retrieved_filings,
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "paused_runs": paused_runs,
        "interrupted_runs": interrupted_runs,
        "extracted_metrics": extracted_metrics,
        "auto_approved_metrics": auto_approved_metrics,
        "validation_checks": validation_checks,
        "failed_validations": failed_validations,
        "warning_validations": warning_validations,
        "open_reviews": open_reviews,
        "total_escalations": total_escalations,
        "resolved_reviews": resolved_reviews,
        "evaluations": evaluations,
        "evaluable_evaluations": evaluable_evaluations,
        "pre_exact_matches": pre_exact_matches,
        "post_exact_matches": post_exact_matches,
        "audit_events": audit_events,
    }


def clear_local_workspace(db_path: Path | str | None = None) -> dict[str, int]:
    """Delete all application rows across core SQLite tables while keeping schema intact.

    Intended strictly for explicitly confirmed workspace resets; never invoke without
    explicit user confirmation.
    """
    deletion_order = (
        "accuracy_evaluations",
        "review_tasks",
        "validation_results",
        "audit_events",
        "extracted_metrics",
        "audit_runs",
        "sec_filings",
        "idempotency_records",
    )
    removed: dict[str, int] = {}
    with get_connection(db_path) as conn:
        for table in deletion_order:
            cursor = conn.execute(f"DELETE FROM {table}")
            removed[table] = int(cursor.rowcount or 0)
    logger.warning("Cleared local FinovaLabs SQLite workspace tables: %s", removed)
    return removed


def fetch_runs(db_path: Path | str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent filing audit runs ordered newest first."""
    return _query_all(
        """
        SELECT run_id, cik, filing_id, accession_number, idempotency_key,
               company_name, ticker, form_type, fiscal_year,
               status, current_stage, overall_confidence,
               created_at, updated_at, error_message
        FROM audit_runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
        db_path=db_path,
    )


def fetch_filing_id(
    cik: str,
    accession_number: str,
    db_path: Path | str | None = None,
) -> int | None:
    """Return sec_filings.id for a retrieved filing if persisted in SQLite."""
    rows = _query_all(
        "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
        (cik, accession_number),
        db_path=db_path,
    )
    return int(rows[0]["id"]) if rows else None


def fetch_audit_run(
    run_id: str,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Return a single audit_runs row by run_id."""
    rows = _query_all(
        """
        SELECT run_id, cik, filing_id, accession_number, idempotency_key,
               company_name, ticker, form_type, fiscal_year,
               status, current_stage, overall_confidence,
               created_at, updated_at, error_message
        FROM audit_runs
        WHERE run_id = ?
        LIMIT 1
        """,
        (run_id,),
        db_path=db_path,
    )
    return rows[0] if rows else None


def fetch_audit_run_by_idempotency_key(
    idempotency_key: str,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Return an existing audit run matching the supplied idempotency key."""
    rows = _query_all(
        """
        SELECT run_id, cik, filing_id, accession_number, idempotency_key,
               company_name, ticker, form_type, fiscal_year,
               status, current_stage, overall_confidence,
               created_at, updated_at, error_message
        FROM audit_runs
        WHERE idempotency_key = ?
        LIMIT 1
        """,
        (idempotency_key,),
        db_path=db_path,
    )
    return rows[0] if rows else None


def fetch_recoverable_workflows(
    db_path: Path | str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return interrupted, running, pending, or paused workflows with open task counts."""
    return _query_all(
        """
        SELECT ar.run_id, ar.cik, ar.filing_id, ar.accession_number, ar.idempotency_key,
               ar.company_name, ar.ticker, ar.form_type, ar.fiscal_year,
               ar.status, ar.current_stage, ar.overall_confidence,
               ar.created_at, ar.updated_at, ar.error_message,
               COUNT(CASE WHEN rt.status = 'OPEN' THEN 1 END) AS open_review_count
        FROM audit_runs ar
        LEFT JOIN review_tasks rt ON rt.run_id = ar.run_id
        WHERE ar.status IN ('PENDING', 'RUNNING', 'INTERRUPTED', 'PAUSED_FOR_REVIEW')
        GROUP BY ar.run_id
        ORDER BY ar.updated_at DESC
        LIMIT ?
        """,
        (limit,),
        db_path=db_path,
    )


def get_idempotency_record(
    idempotency_key: str,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Lookup an existing idempotency record by key."""
    rows = _query_all(
        """
        SELECT idempotency_key, scope, target_id, result_json, created_at
        FROM idempotency_records
        WHERE idempotency_key = ?
        LIMIT 1
        """,
        (idempotency_key,),
        db_path=db_path,
    )
    return rows[0] if rows else None


def claim_idempotency_key(
    *,
    idempotency_key: str,
    scope: str,
    target_id: str,
    result_json: str | None = None,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Atomically claim an idempotency key; returns (True, None) if new else (False, existing_row)."""
    now = datetime.now(timezone.utc).isoformat()
    with _optional_transaction(conn, db_path) as active_conn:
        cur = active_conn.execute(
            """
            INSERT INTO idempotency_records (idempotency_key, scope, target_id, result_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (idempotency_key, scope, target_id, result_json, now),
        )
        if cur.rowcount == 1:
            return True, None
        row = active_conn.execute(
            """
            SELECT idempotency_key, scope, target_id, result_json, created_at
            FROM idempotency_records
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        return False, (dict(row) if row else None)


def update_idempotency_result(
    *,
    idempotency_key: str,
    target_id: str,
    result_json: str | None,
    db_path: Path | str | None = None,
) -> None:
    """Update cached result payload on a claimed idempotency record."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE idempotency_records
            SET target_id = ?, result_json = ?
            WHERE idempotency_key = ?
            """,
            (target_id, result_json, idempotency_key),
        )


def fetch_extracted_metrics(
    run_id: str | None = None,
    accession_number: str | None = None,
    db_path: Path | str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return extracted financial metrics, optionally filtered by run_id or accession_number."""
    clauses: list[str] = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if accession_number:
        clauses.append("accession_number = ?")
        params.append(accession_number)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order_sql = "ORDER BY id ASC" if (run_id or accession_number) else "ORDER BY id DESC"
    params.append(limit)
    return _query_all(
        f"""
        SELECT id, run_id, cik, ticker, accession_number, form_type,
               metric_name, xbrl_concept, raw_value, normalized_value, normalized_decimal,
               unit, currency, scale_factor, fiscal_period, fiscal_year,
               period_start, period_end, source_url, source_evidence, evidence_location,
               extraction_status, candidates_json, confidence_score,
               confidence_components_json, confidence_reasons,
               confidence_threshold, scoring_version,
               validation_status, review_status,
               reviewed_value, reviewed_decimal, reviewer_note, reviewed_by, reviewed_at,
               created_at
        FROM extracted_metrics
        {where_sql}
        {order_sql}
        LIMIT ?
        """,
        tuple(params),
        db_path=db_path,
    )


def save_extracted_metrics(
    records: list[dict[str, Any]],
    cik: str,
    accession_number: str,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist extracted metrics for a specific filing, replacing prior rows for that filing."""
    with _optional_transaction(conn, db_path) as active_conn:
        active_conn.execute(
            "DELETE FROM extracted_metrics WHERE cik = ? AND accession_number = ?",
            (cik, accession_number),
        )
        for rec in records:
            active_conn.execute(
                """
                INSERT INTO extracted_metrics (
                    run_id, cik, ticker, accession_number, form_type,
                    metric_name, xbrl_concept, raw_value, normalized_value, normalized_decimal,
                    unit, currency, scale_factor, fiscal_period, fiscal_year,
                    period_start, period_end, source_url, source_evidence, evidence_location,
                    extraction_status, candidates_json, confidence_score,
                    confidence_components_json, confidence_reasons,
                    confidence_threshold, scoring_version,
                    validation_status, review_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get("run_id"),
                    cik,
                    rec.get("ticker"),
                    accession_number,
                    rec.get("form_type"),
                    rec["metric_name"],
                    rec.get("xbrl_concept"),
                    rec.get("raw_value"),
                    rec.get("normalized_value"),
                    rec.get("normalized_decimal"),
                    rec.get("unit", "USD"),
                    rec.get("currency", "USD"),
                    rec.get("scale_factor", 1),
                    rec.get("fiscal_period"),
                    rec.get("fiscal_year"),
                    rec.get("period_start"),
                    rec.get("period_end"),
                    rec.get("source_url"),
                    rec.get("source_evidence"),
                    rec.get("evidence_location"),
                    rec.get("extraction_status", "EXTRACTED"),
                    rec.get("candidates_json"),
                    rec.get("confidence_score"),
                    rec.get("confidence_components_json"),
                    rec.get("confidence_reasons"),
                    rec.get("confidence_threshold"),
                    rec.get("scoring_version"),
                    rec.get("validation_status", "PENDING"),
                    rec.get("review_status", "NOT_REQUIRED"),
                    rec["created_at"],
                ),
            )
    return len(records)


def save_validation_results(
    results: list[dict[str, Any]],
    cik: str,
    accession_number: str,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist financial validation results for a filing, replacing prior validation rows for that filing."""
    with _optional_transaction(conn, db_path) as active_conn:
        active_conn.execute(
            "DELETE FROM validation_results WHERE cik = ? AND accession_number = ?",
            (cik, accession_number),
        )
        for item in results:
            val_id = item.get("validation_id") or f"val-{uuid.uuid4().hex[:10]}"
            active_conn.execute(
                """
                INSERT INTO validation_results (
                    validation_id, run_id, cik, ticker, accession_number,
                    rule_name, metric_name, status, explanation, input_metric_refs_json,
                    expected_value, actual_value, variance_abs, variance_pct,
                    tolerance_used, escalated, evaluated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    val_id,
                    item.get("run_id"),
                    cik,
                    item.get("ticker"),
                    accession_number,
                    item["rule_name"],
                    item["metric_name"],
                    item["status"],
                    item["explanation"],
                    item["input_metric_refs_json"],
                    item.get("expected_value"),
                    item.get("actual_value"),
                    item.get("variance_abs"),
                    item.get("variance_pct"),
                    item.get("tolerance_used"),
                    1 if item.get("escalated") else 0,
                    item["evaluated_at"],
                ),
            )
    return len(results)


def fetch_validation_results(
    accession_number: str | None = None,
    status: str | None = None,
    db_path: Path | str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return persisted financial validation results, optionally filtered by accession or status."""
    clauses: list[str] = []
    params: list[Any] = []
    if accession_number:
        clauses.append("accession_number = ?")
        params.append(accession_number)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _query_all(
        f"""
        SELECT validation_id, run_id, cik, ticker, accession_number,
               rule_name, metric_name, status, explanation, input_metric_refs_json,
               expected_value, actual_value, variance_abs, variance_pct,
               tolerance_used, escalated, evaluated_at
        FROM validation_results
        {where_sql}
        ORDER BY evaluated_at DESC, validation_id ASC
        LIMIT ?
        """,
        tuple(params),
        db_path=db_path,
    )


def apply_validation_outcomes_to_filing(
    *,
    cik: str,
    ticker: str | None,
    accession_number: str,
    metric_validation_statuses: dict[str, str],
    failure_escalations: list[dict[str, Any]],
    run_id: str | None = None,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Update extracted_metrics.validation_status and open review tasks for FAIL validations."""
    created_tasks = 0
    with _optional_transaction(conn, db_path) as active_conn:
        for metric_name, val_status in metric_validation_statuses.items():
            if val_status == "FAIL":
                active_conn.execute(
                    """
                    UPDATE extracted_metrics
                    SET validation_status = 'FAIL', review_status = 'REVIEW_REQUIRED'
                    WHERE cik = ? AND accession_number = ? AND metric_name = ?
                    """,
                    (cik, accession_number, metric_name),
                )
            else:
                active_conn.execute(
                    """
                    UPDATE extracted_metrics
                    SET validation_status = ?
                    WHERE cik = ? AND accession_number = ? AND metric_name = ?
                    """,
                    (val_status, cik, accession_number, metric_name),
                )

        # Remove prior validation-triggered OPEN tasks for this filing to remain idempotent
        active_conn.execute(
            """
            DELETE FROM review_tasks
            WHERE cik = ? AND accession_number = ? AND status = 'OPEN'
              AND reason LIKE '[Validation FAIL]%'
            """,
            (cik, accession_number),
        )
        metric_rows = active_conn.execute(
            "SELECT id, metric_name FROM extracted_metrics WHERE cik = ? AND accession_number = ?",
            (cik, accession_number),
        ).fetchall()
        metric_id_by_name = {row["metric_name"]: row["id"] for row in metric_rows}

        for item in failure_escalations:
            metric_name = item["metric_name"]
            reason = item["reason"]
            if not reason.startswith("[Validation FAIL]"):
                reason = f"[Validation FAIL] {reason}"
            existing = active_conn.execute(
                """
                SELECT task_id FROM review_tasks
                WHERE cik = ? AND accession_number = ? AND metric_name = ?
                  AND status = 'OPEN' AND reason = ?
                """,
                (cik, accession_number, metric_name, reason),
            ).fetchone()
            if existing is not None:
                continue
            active_conn.execute(
                """
                INSERT INTO review_tasks (
                    task_id, run_id, cik, ticker, accession_number,
                    metric_id, metric_name, reason, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    f"rev-{uuid.uuid4().hex[:10]}",
                    run_id,
                    cik,
                    ticker,
                    accession_number,
                    metric_id_by_name.get(metric_name),
                    metric_name,
                    reason,
                    item.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
            created_tasks += 1
    return created_tasks


def sync_review_tasks_for_filing(
    tasks: list[dict[str, Any]],
    cik: str,
    accession_number: str,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Replace OPEN review tasks for a filing with newly escalated confidence/extraction items."""
    with _optional_transaction(conn, db_path) as active_conn:
        active_conn.execute(
            "DELETE FROM review_tasks WHERE cik = ? AND accession_number = ? AND status = 'OPEN'",
            (cik, accession_number),
        )
        metric_rows = active_conn.execute(
            "SELECT id, metric_name FROM extracted_metrics WHERE cik = ? AND accession_number = ?",
            (cik, accession_number),
        ).fetchall()
        metric_id_by_name = {row["metric_name"]: row["id"] for row in metric_rows}

        inserted = 0
        for item in tasks:
            metric_name = item["metric_name"]
            task_id = item.get("task_id") or f"rev-{uuid.uuid4().hex[:10]}"
            active_conn.execute(
                """
                INSERT INTO review_tasks (
                    task_id, run_id, cik, ticker, accession_number,
                    metric_id, metric_name, reason, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    task_id,
                    item.get("run_id"),
                    cik,
                    item.get("ticker"),
                    accession_number,
                    item.get("metric_id") or metric_id_by_name.get(metric_name),
                    metric_name,
                    item["reason"],
                    item.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
            inserted += 1
    return inserted


def fetch_review_tasks(
    status: str | None = None,
    run_id: str | None = None,
    db_path: Path | str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return human-in-the-loop review tasks joined with full metric and filing context."""
    base_sql = """
        SELECT rt.task_id, rt.run_id,
               COALESCE(rt.cik, em.cik) AS cik,
               COALESCE(rt.ticker, em.ticker) AS ticker,
               sf.company_name,
               sf.filing_date,
               COALESCE(rt.accession_number, em.accession_number) AS accession_number,
               em.form_type,
               rt.metric_id,
               COALESCE(rt.metric_name, em.metric_name) AS metric_name,
               em.raw_value,
               em.normalized_value,
               em.normalized_decimal,
               em.unit,
               em.currency,
               em.scale_factor,
               em.fiscal_period,
               em.fiscal_year,
               em.period_start,
               em.period_end,
               em.source_url,
               em.source_evidence,
               em.evidence_location,
               em.confidence_score,
               em.confidence_threshold,
               em.scoring_version,
               em.extraction_status,
               em.validation_status,
               em.review_status,
               em.reviewed_value,
               em.reviewed_decimal,
               rt.reason,
               rt.status,
               rt.reviewer_note,
               rt.resolved_value,
               rt.resolved_decimal,
               rt.resolved_by,
               rt.created_at,
               rt.resolved_at
        FROM review_tasks rt
        LEFT JOIN extracted_metrics em ON em.id = rt.metric_id
        LEFT JOIN sec_filings sf
          ON sf.cik = COALESCE(rt.cik, em.cik)
         AND sf.accession_number = COALESCE(rt.accession_number, em.accession_number)
    """
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        status_clean = str(status).upper().strip()
        if status_clean in ("PENDING", "OPEN"):
            clauses.append("rt.status = 'OPEN'")
        elif status_clean in ("RESOLVED", "CLOSED"):
            clauses.append("rt.status IN ('APPROVED', 'CORRECTED', 'REJECTED')")
        else:
            clauses.append("rt.status = ?")
            params.append(status_clean)
    if run_id:
        clauses.append("rt.run_id = ?")
        params.append(run_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _query_all(
        f"{base_sql} {where_sql} ORDER BY rt.created_at DESC LIMIT ?",
        tuple(params),
        db_path=db_path,
    )


def create_audit_run(
    *,
    run_id: str,
    cik: str,
    filing_id: int | None = None,
    accession_number: str | None = None,
    idempotency_key: str | None = None,
    company_name: str | None,
    ticker: str | None,
    form_type: str = "10-K",
    fiscal_year: int | None = None,
    status: str = "RUNNING",
    current_stage: str = "STARTED",
    overall_confidence: float | None = None,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Create or upsert an audit_runs record at workflow start with filing & idempotency linkage."""
    now = datetime.now(timezone.utc).isoformat()
    with _optional_transaction(conn, db_path) as active_conn:
        resolved_filing_id = filing_id
        if resolved_filing_id is None and accession_number:
            frow = active_conn.execute(
                "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ? LIMIT 1",
                (cik, accession_number),
            ).fetchone()
            resolved_filing_id = int(frow["id"]) if frow else None
        active_conn.execute(
            """
            INSERT INTO audit_runs (
                run_id, cik, filing_id, accession_number, idempotency_key,
                company_name, ticker, form_type, fiscal_year,
                status, current_stage, overall_confidence,
                created_at, updated_at, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(run_id) DO UPDATE SET
                filing_id = COALESCE(excluded.filing_id, audit_runs.filing_id),
                accession_number = COALESCE(excluded.accession_number, audit_runs.accession_number),
                idempotency_key = COALESCE(excluded.idempotency_key, audit_runs.idempotency_key),
                status = excluded.status,
                current_stage = excluded.current_stage,
                overall_confidence = COALESCE(excluded.overall_confidence, audit_runs.overall_confidence),
                updated_at = excluded.updated_at
            """,
            (
                run_id,
                cik,
                resolved_filing_id,
                accession_number,
                idempotency_key,
                company_name,
                ticker,
                form_type,
                fiscal_year,
                status,
                current_stage,
                overall_confidence,
                now,
                now,
            ),
        )


def update_audit_run_status(
    *,
    run_id: str,
    status: str,
    current_stage: str | None = None,
    overall_confidence: float | None = None,
    error_message: str | None = None,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update persisted workflow status, stage checkpoint label, and timestamps for an audit run."""
    now = datetime.now(timezone.utc).isoformat()
    with _optional_transaction(conn, db_path) as active_conn:
        active_conn.execute(
            """
            UPDATE audit_runs
            SET status = ?,
                current_stage = COALESCE(?, current_stage),
                overall_confidence = COALESCE(?, overall_confidence),
                error_message = ?,
                updated_at = ?
            WHERE run_id = ?
            """,
            (status, current_stage, overall_confidence, error_message, now, run_id),
        )


def fetch_open_review_count_for_run(
    run_id: str,
    db_path: Path | str | None = None,
) -> int:
    """Return the count of remaining OPEN review tasks for an audit run."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM review_tasks WHERE run_id = ? AND status = 'OPEN'",
            (run_id,),
        ).fetchone()
        return int(row["c"]) if row else 0


def _validate_review_decision_inputs(
    *,
    action: str,
    reviewer_note: str,
    corrected_value: Decimal | str | float | int | None,
    orig_dec: str | None,
    orig_float: float | None,
) -> tuple[str, str, str | None, float | None, str]:
    """Validate and normalize human review action, note, and target Decimal/float value."""
    normalized_action = action.strip().upper()
    if normalized_action in {"EDIT/CORRECT", "CORRECT", "EDIT"}:
        normalized_action = "EDIT"
    if normalized_action not in {"APPROVE", "EDIT", "REJECT"}:
        raise ValueError(f"Unsupported review action '{action}'. Expected APPROVE, EDIT, or REJECT.")

    clean_note = (reviewer_note or "").strip()
    if normalized_action in {"EDIT", "REJECT"} and not clean_note:
        raise ValueError(f"An explanation note is required for {normalized_action} actions.")

    resolved_dec: str | None = None
    resolved_float: float | None = None
    if normalized_action == "APPROVE":
        task_status = "APPROVED"
        resolved_dec = orig_dec
        resolved_float = orig_float
        if resolved_dec is None and resolved_float is not None:
            resolved_dec = str(resolved_float)
    elif normalized_action == "EDIT":
        if corrected_value is None or str(corrected_value).strip() == "":
            raise ValueError("A numeric corrected value is required for EDIT/CORRECT actions.")
        try:
            dec_val = Decimal(str(corrected_value).replace(",", "").strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid corrected numeric value '{corrected_value}'.") from exc
        if not dec_val.is_finite():
            raise ValueError("Corrected value must be a finite number.")
        task_status = "CORRECTED"
        resolved_dec = str(dec_val)
        resolved_float = float(dec_val)
    else:
        task_status = "REJECTED"
    return normalized_action, task_status, resolved_dec, resolved_float, clean_note


def record_human_review_decision(
    *,
    task_id: str,
    action: str,
    reviewer_note: str = "",
    corrected_value: Decimal | str | float | int | None = None,
    reviewer: str = "analyst",
    session_id: str | None = None,
    decision_key: str | None = None,
    allow_amendment: bool = False,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Persist APPROVE/EDIT/REJECT and its append-only audit event atomically in one transaction."""
    from finova_labs.audit import record_audit_event

    clean_reviewer = (reviewer or "analyst").strip() or "analyst"
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        task_row = conn.execute(
            """
            SELECT rt.*,
                   em.normalized_value AS orig_float,
                   em.normalized_decimal AS orig_dec,
                   em.raw_value AS orig_raw,
                   em.unit AS orig_unit,
                   em.reviewed_decimal AS prev_reviewed_dec,
                   em.review_status AS prev_metric_review_status,
                   sf.id AS filing_id,
                   COALESCE(sf.company_name, ar.company_name) AS company_name
            FROM review_tasks rt
            LEFT JOIN extracted_metrics em ON em.id = rt.metric_id
            LEFT JOIN sec_filings sf
              ON sf.cik = COALESCE(rt.cik, em.cik)
             AND sf.accession_number = COALESCE(rt.accession_number, em.accession_number)
            LEFT JOIN audit_runs ar ON ar.run_id = rt.run_id
            WHERE rt.task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if task_row is None:
            raise ValueError(f"Review task '{task_id}' was not found.")

        normalized_action, task_status, resolved_dec, resolved_float, clean_note = (
            _validate_review_decision_inputs(
                action=action,
                reviewer_note=reviewer_note,
                corrected_value=corrected_value,
                orig_dec=task_row["orig_dec"],
                orig_float=task_row["orig_float"],
            )
        )

        computed_key = decision_key or hashlib.sha256(
            f"{task_id}|{task_status}|{resolved_dec or ''}|{clean_note}".encode("utf-8")
        ).hexdigest()[:24]

        is_amendment = False
        effective_task_id = task_id
        if task_row["status"] != "OPEN":
            same_key = task_row["decision_key"] is not None and task_row["decision_key"] == computed_key
            same_outcome = (
                task_row["status"] == task_status
                and (task_row["resolved_decimal"] or None) == resolved_dec
                and (task_row["reviewer_note"] or "") == clean_note
            )
            if same_key or same_outcome:
                return {
                    "task_id": task_id,
                    "run_id": task_row["run_id"],
                    "cik": task_row["cik"],
                    "ticker": task_row["ticker"],
                    "company_name": task_row["company_name"],
                    "filing_id": task_row["filing_id"],
                    "accession_number": task_row["accession_number"],
                    "metric_id": task_row["metric_id"],
                    "metric_name": task_row["metric_name"],
                    "action": normalized_action,
                    "status": task_row["status"],
                    "original_decimal": task_row["orig_dec"],
                    "original_value": task_row["orig_float"],
                    "resolved_decimal": task_row["resolved_decimal"],
                    "resolved_value": task_row["resolved_value"],
                    "reviewer_note": task_row["reviewer_note"],
                    "resolved_by": task_row["resolved_by"],
                    "resolved_at": task_row["resolved_at"],
                    "decision_key": task_row["decision_key"] or computed_key,
                    "idempotent_replay": True,
                }
            if not allow_amendment:
                raise ValueError(
                    f"Review task '{task_id}' is already resolved with status '{task_row['status']}'."
                )
            is_amendment = True
            effective_task_id = f"rev-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO review_tasks (
                    task_id, run_id, cik, ticker, accession_number,
                    metric_id, metric_name, reason, status,
                    reviewer_note, resolved_value, resolved_decimal,
                    resolved_by, decision_key, created_at, resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    effective_task_id,
                    task_row["run_id"],
                    task_row["cik"],
                    task_row["ticker"],
                    task_row["accession_number"],
                    task_row["metric_id"],
                    task_row["metric_name"],
                    f"[Subsequent Amendment of {task_id} ({task_row['status']})] {clean_note or normalized_action}",
                    task_status,
                    clean_note or None,
                    resolved_float,
                    resolved_dec,
                    clean_reviewer,
                    computed_key,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = ?,
                    reviewer_note = ?,
                    resolved_value = ?,
                    resolved_decimal = ?,
                    resolved_by = ?,
                    decision_key = ?,
                    resolved_at = ?
                WHERE task_id = ?
                """,
                (
                    task_status,
                    clean_note or None,
                    resolved_float,
                    resolved_dec,
                    clean_reviewer,
                    computed_key,
                    now,
                    task_id,
                ),
            )

        # Update ONLY review overlay columns on extracted_metrics; NEVER mutate raw_value,
        # normalized_value, or normalized_decimal so the original extracted value is permanent.
        metric_id = task_row["metric_id"]
        if metric_id is not None:
            remaining_same_metric = conn.execute(
                """
                SELECT COUNT(*) AS c FROM review_tasks
                WHERE metric_id = ? AND status = 'OPEN' AND task_id != ?
                """,
                (metric_id, effective_task_id),
            ).fetchone()
            other_open = int(remaining_same_metric["c"]) if remaining_same_metric else 0
            new_metric_review_status = task_status if other_open == 0 else "REVIEW_REQUIRED"
            conn.execute(
                """
                UPDATE extracted_metrics
                SET review_status = ?,
                    reviewed_value = ?,
                    reviewed_decimal = ?,
                    reviewer_note = ?,
                    reviewed_by = ?,
                    reviewed_at = ?
                WHERE id = ?
                """,
                (
                    new_metric_review_status,
                    resolved_float,
                    resolved_dec,
                    clean_note or None,
                    clean_reviewer,
                    now,
                    metric_id,
                ),
            )

        orig_display_val = (
            task_row["orig_dec"]
            if task_row["orig_dec"] is not None
            else (str(task_row["orig_float"]) if task_row["orig_float"] is not None else None)
        )
        explanation_text = clean_note or f"Human analyst {task_status.lower()} extracted metric value."
        audit_event_id = record_audit_event(
            event_type="HUMAN_REVIEW_DECISION",
            actor=clean_reviewer,
            run_id=task_row["run_id"],
            cik=task_row["cik"],
            ticker=task_row["ticker"],
            company_name=task_row["company_name"],
            filing_id=task_row["filing_id"],
            accession_number=task_row["accession_number"],
            metric_id=metric_id,
            metric_name=task_row["metric_name"],
            decision=task_status,
            original_value=orig_display_val,
            corrected_value=resolved_dec if normalized_action == "EDIT" else None,
            reviewer_id=clean_reviewer,
            session_id=session_id,
            explanation=explanation_text,
            created_at=now,
            payload={
                "task_id": effective_task_id,
                "supersedes_task_id": task_id if is_amendment else None,
                "is_subsequent_correction": is_amendment,
                "previous_reviewed_decimal": task_row["prev_reviewed_dec"] if is_amendment else None,
                "cik": task_row["cik"],
                "ticker": task_row["ticker"],
                "company_name": task_row["company_name"],
                "filing_id": task_row["filing_id"],
                "accession_number": task_row["accession_number"],
                "metric_id": metric_id,
                "metric_name": task_row["metric_name"],
                "action": normalized_action,
                "status": task_status,
                "decision_key": computed_key,
                "original_decimal": task_row["orig_dec"],
                "resolved_decimal": resolved_dec,
                "corrected_decimal": resolved_dec if normalized_action == "EDIT" else None,
                "reviewer_id": clean_reviewer,
                "reviewer_note": clean_note or None,
            },
            conn=conn,
        )

    return {
        "task_id": effective_task_id,
        "run_id": task_row["run_id"],
        "cik": task_row["cik"],
        "ticker": task_row["ticker"],
        "company_name": task_row["company_name"],
        "filing_id": task_row["filing_id"],
        "accession_number": task_row["accession_number"],
        "metric_id": task_row["metric_id"],
        "metric_name": task_row["metric_name"],
        "action": normalized_action,
        "status": task_status,
        "original_decimal": task_row["orig_dec"],
        "original_value": task_row["orig_float"],
        "resolved_decimal": resolved_dec,
        "resolved_value": resolved_float,
        "reviewer_note": clean_note or None,
        "resolved_by": clean_reviewer,
        "resolved_at": now,
        "decision_key": computed_key,
        "audit_event_id": audit_event_id,
        "is_subsequent_correction": is_amendment,
        "idempotent_replay": False,
    }


def amend_metric_review_decision(
    *,
    metric_id: int,
    action: str = "EDIT",
    reviewer_note: str = "",
    corrected_value: Decimal | str | float | int | None = None,
    reviewer: str = "analyst",
    session_id: str | None = None,
    decision_key: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Append a subsequent human review decision/correction for a metric in one atomic transaction.

    Prior audit_events and earlier resolved review_tasks remain completely untouched while
    the metric's current review overlay is updated (preserving normalized_decimal permanently).
    """
    from finova_labs.audit import record_audit_event

    clean_reviewer = (reviewer or "analyst").strip() or "analyst"
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        metric_row = conn.execute(
            """
            SELECT em.*,
                   sf.id AS filing_id,
                   COALESCE(sf.company_name, ar.company_name) AS company_name
            FROM extracted_metrics em
            LEFT JOIN sec_filings sf
              ON sf.cik = em.cik AND sf.accession_number = em.accession_number
            LEFT JOIN audit_runs ar ON ar.run_id = em.run_id
            WHERE em.id = ?
            """,
            (metric_id,),
        ).fetchone()
        if metric_row is None:
            raise ValueError(f"Metric record '{metric_id}' was not found.")

        normalized_action, task_status, resolved_dec, resolved_float, clean_note = (
            _validate_review_decision_inputs(
                action=action,
                reviewer_note=reviewer_note,
                corrected_value=corrected_value,
                orig_dec=metric_row["normalized_decimal"],
                orig_float=metric_row["normalized_value"],
            )
        )

        new_task_id = f"rev-{uuid.uuid4().hex[:10]}"
        computed_key = decision_key or hashlib.sha256(
            f"metric:{metric_id}|{task_status}|{resolved_dec or ''}|{clean_note}|{now}".encode("utf-8")
        ).hexdigest()[:24]

        # Idempotent replay if a review_tasks record already used an explicit decision_key
        if decision_key:
            existing_task = conn.execute(
                "SELECT * FROM review_tasks WHERE decision_key = ? LIMIT 1",
                (decision_key,),
            ).fetchone()
            if existing_task is not None:
                return {
                    "task_id": existing_task["task_id"],
                    "run_id": existing_task["run_id"],
                    "cik": existing_task["cik"],
                    "ticker": existing_task["ticker"],
                    "company_name": metric_row["company_name"],
                    "filing_id": metric_row["filing_id"],
                    "accession_number": existing_task["accession_number"],
                    "metric_id": metric_id,
                    "metric_name": metric_row["metric_name"],
                    "action": normalized_action,
                    "status": existing_task["status"],
                    "original_decimal": metric_row["normalized_decimal"],
                    "original_value": metric_row["normalized_value"],
                    "resolved_decimal": existing_task["resolved_decimal"],
                    "resolved_value": existing_task["resolved_value"],
                    "reviewer_note": existing_task["reviewer_note"],
                    "resolved_by": existing_task["resolved_by"],
                    "resolved_at": existing_task["resolved_at"],
                    "decision_key": decision_key,
                    "is_subsequent_correction": True,
                    "idempotent_replay": True,
                }

        conn.execute(
            """
            INSERT INTO review_tasks (
                task_id, run_id, cik, ticker, accession_number,
                metric_id, metric_name, reason, status,
                reviewer_note, resolved_value, resolved_decimal,
                resolved_by, decision_key, created_at, resolved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_task_id,
                metric_row["run_id"],
                metric_row["cik"],
                metric_row["ticker"],
                metric_row["accession_number"],
                metric_id,
                metric_row["metric_name"],
                f"[Subsequent Review ({metric_row['review_status']})] {clean_note or normalized_action}",
                task_status,
                clean_note or None,
                resolved_float,
                resolved_dec,
                clean_reviewer,
                computed_key,
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE extracted_metrics
            SET review_status = ?,
                reviewed_value = ?,
                reviewed_decimal = ?,
                reviewer_note = ?,
                reviewed_by = ?,
                reviewed_at = ?
            WHERE id = ?
            """,
            (
                task_status,
                resolved_float,
                resolved_dec,
                clean_note or None,
                clean_reviewer,
                now,
                metric_id,
            ),
        )

        orig_display_val = (
            metric_row["normalized_decimal"]
            if metric_row["normalized_decimal"] is not None
            else (str(metric_row["normalized_value"]) if metric_row["normalized_value"] is not None else None)
        )
        explanation_text = clean_note or f"Subsequent analyst {task_status.lower()} review."
        audit_event_id = record_audit_event(
            event_type="HUMAN_REVIEW_DECISION",
            actor=clean_reviewer,
            run_id=metric_row["run_id"],
            cik=metric_row["cik"],
            ticker=metric_row["ticker"],
            company_name=metric_row["company_name"],
            filing_id=metric_row["filing_id"],
            accession_number=metric_row["accession_number"],
            metric_id=metric_id,
            metric_name=metric_row["metric_name"],
            decision=task_status,
            original_value=orig_display_val,
            corrected_value=resolved_dec if normalized_action == "EDIT" else None,
            reviewer_id=clean_reviewer,
            session_id=session_id,
            explanation=explanation_text,
            created_at=now,
            payload={
                "task_id": new_task_id,
                "is_subsequent_correction": True,
                "previous_review_status": metric_row["review_status"],
                "previous_reviewed_decimal": metric_row["reviewed_decimal"],
                "cik": metric_row["cik"],
                "ticker": metric_row["ticker"],
                "company_name": metric_row["company_name"],
                "filing_id": metric_row["filing_id"],
                "accession_number": metric_row["accession_number"],
                "metric_id": metric_id,
                "metric_name": metric_row["metric_name"],
                "action": normalized_action,
                "status": task_status,
                "decision_key": computed_key,
                "original_decimal": metric_row["normalized_decimal"],
                "resolved_decimal": resolved_dec,
                "corrected_decimal": resolved_dec if normalized_action == "EDIT" else None,
                "reviewer_id": clean_reviewer,
                "reviewer_note": clean_note or None,
            },
            conn=conn,
        )

    return {
        "task_id": new_task_id,
        "run_id": metric_row["run_id"],
        "cik": metric_row["cik"],
        "ticker": metric_row["ticker"],
        "company_name": metric_row["company_name"],
        "filing_id": metric_row["filing_id"],
        "accession_number": metric_row["accession_number"],
        "metric_id": metric_id,
        "metric_name": metric_row["metric_name"],
        "action": normalized_action,
        "status": task_status,
        "original_decimal": metric_row["normalized_decimal"],
        "original_value": metric_row["normalized_value"],
        "resolved_decimal": resolved_dec,
        "resolved_value": resolved_float,
        "reviewer_note": clean_note or None,
        "resolved_by": clean_reviewer,
        "resolved_at": now,
        "decision_key": computed_key,
        "audit_event_id": audit_event_id,
        "is_subsequent_correction": True,
        "idempotent_replay": False,
    }


def _write_accuracy_evaluations(
    conn: sqlite3.Connection,
    evaluations: list[dict[str, Any]],
    *,
    run_id: str,
) -> int:
    conn.execute("DELETE FROM accuracy_evaluations WHERE run_id = ?", (run_id,))
    for row in evaluations:
        conn.execute(
            """
            INSERT INTO accuracy_evaluations (
                run_id, metric_id, cik, ticker, company_name, accession_number, form_type,
                metric_name, xbrl_concept, unit, fiscal_period, fiscal_year,
                period_start, period_end, extracted_value, pre_review_decimal,
                post_review_decimal, review_status, ground_truth_value, ground_truth_decimal,
                ground_truth_unit, ground_truth_concept, ground_truth_fiscal_period,
                ground_truth_period_start, ground_truth_period_end, ground_truth_accession,
                abs_diff, rel_diff, matched, pre_abs_diff, pre_pct_diff, pre_exact_match,
                pre_status, post_abs_diff, post_pct_diff, post_exact_match, post_status,
                comparison_status, explanation, reference_source_url, reference_fact_json,
                evaluated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id,
                row.get("metric_id"),
                row.get("cik"),
                row.get("ticker"),
                row.get("company_name"),
                row.get("accession_number"),
                row.get("form_type"),
                row["metric_name"],
                row.get("xbrl_concept"),
                row.get("unit"),
                row.get("fiscal_period"),
                row.get("fiscal_year"),
                row.get("period_start"),
                row.get("period_end"),
                row.get("extracted_value"),
                row.get("pre_review_decimal"),
                row.get("post_review_decimal"),
                row.get("review_status"),
                row.get("ground_truth_value"),
                row.get("ground_truth_decimal"),
                row.get("ground_truth_unit"),
                row.get("ground_truth_concept"),
                row.get("ground_truth_fiscal_period"),
                row.get("ground_truth_period_start"),
                row.get("ground_truth_period_end"),
                row.get("ground_truth_accession"),
                row.get("abs_diff"),
                row.get("rel_diff"),
                int(bool(row.get("matched", 0))),
                row.get("pre_abs_diff"),
                row.get("pre_pct_diff"),
                int(bool(row.get("pre_exact_match", 0))),
                row.get("pre_status", "UNAVAILABLE_REFERENCE"),
                row.get("post_abs_diff"),
                row.get("post_pct_diff"),
                int(bool(row.get("post_exact_match", 0))),
                row.get("post_status", "UNAVAILABLE_REFERENCE"),
                row.get("comparison_status", "UNAVAILABLE_REFERENCE"),
                row.get("explanation"),
                row.get("reference_source_url"),
                row.get("reference_fact_json"),
                row["evaluated_at"],
            ),
        )
    return len(evaluations)


def save_accuracy_evaluations(
    evaluations: list[dict[str, Any]],
    *,
    run_id: str,
    db_path: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Replace accuracy evaluation rows for a single audit run in one transaction."""
    if conn is not None:
        return _write_accuracy_evaluations(conn, evaluations, run_id=run_id)
    with get_connection(db_path) as active_conn:
        return _write_accuracy_evaluations(active_conn, evaluations, run_id=run_id)


def fetch_accuracy_evaluations(
    run_id: str | None = None,
    cik: str | None = None,
    db_path: Path | str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return Company Facts benchmark evaluations with pre/post review and reference provenance."""
    base_select = """
        SELECT ae.eval_id, ae.run_id, ae.metric_id,
               COALESCE(ae.cik, ar.cik) AS cik,
               COALESCE(ae.ticker, ar.ticker) AS ticker,
               COALESCE(ae.company_name, ar.company_name) AS company_name,
               COALESCE(ae.accession_number, ar.accession_number) AS accession_number,
               COALESCE(ae.form_type, ar.form_type) AS form_type,
               ae.metric_name, ae.xbrl_concept, ae.unit,
               ae.fiscal_period, ae.fiscal_year, ae.period_start, ae.period_end,
               ae.extracted_value, ae.pre_review_decimal, ae.post_review_decimal,
               ae.review_status, ae.ground_truth_value, ae.ground_truth_decimal,
               ae.ground_truth_unit, ae.ground_truth_concept, ae.ground_truth_fiscal_period,
               ae.ground_truth_period_start, ae.ground_truth_period_end, ae.ground_truth_accession,
               ae.abs_diff, ae.rel_diff, ae.matched,
               ae.pre_abs_diff, ae.pre_pct_diff, ae.pre_exact_match, ae.pre_status,
               ae.post_abs_diff, ae.post_pct_diff, ae.post_exact_match, ae.post_status,
               ae.comparison_status, ae.explanation, ae.reference_source_url,
               ae.reference_fact_json, ae.evaluated_at
        FROM accuracy_evaluations ae
        LEFT JOIN audit_runs ar ON ar.run_id = ae.run_id
    """
    clauses: list[str] = []
    params: list[Any] = []
    if run_id:
        clauses.append("ae.run_id = ?")
        params.append(run_id)
    if cik:
        clauses.append("COALESCE(ae.cik, ar.cik) = ?")
        params.append(cik)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order_sql = "ORDER BY ae.eval_id ASC" if run_id else "ORDER BY ae.eval_id DESC"
    params.append(limit)
    return _query_all(
        f"{base_select} {where_sql} {order_sql} LIMIT ?",
        tuple(params),
        db_path=db_path,
    )


_DECISION_FILTER_ALIASES: dict[str, tuple[str, ...]] = {
    "APPROVE": ("APPROVE", "APPROVED"),
    "APPROVED": ("APPROVE", "APPROVED"),
    "EDIT": ("EDIT", "CORRECT", "CORRECTED", "EDIT/CORRECT"),
    "CORRECT": ("EDIT", "CORRECT", "CORRECTED", "EDIT/CORRECT"),
    "CORRECTED": ("EDIT", "CORRECT", "CORRECTED", "EDIT/CORRECT"),
    "REJECT": ("REJECT", "REJECTED"),
    "REJECTED": ("REJECT", "REJECTED"),
    "AUTO_APPROVE": ("AUTO_APPROVE", "AUTO_APPROVED"),
    "AUTO_APPROVED": ("AUTO_APPROVE", "AUTO_APPROVED"),
    "ESCALATE": ("ESCALATE", "ESCALATED"),
    "ESCALATED": ("ESCALATE", "ESCALATED"),
}


def fetch_audit_events(
    run_id: str | None = None,
    db_path: Path | str | None = None,
    limit: int = 100,
    *,
    company: str | None = None,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    decision: str | None = None,
    metric_name: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
) -> list[dict[str, Any]]:
    """Return append-only hash-chained audit events ordered newest first with SQL filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if company and company.strip():
        comp_upper = company.strip().upper()
        comp_like = f"%{company.strip().lower()}%"
        clauses.append(
            "(UPPER(COALESCE(ticker, '')) = ? OR cik = ? OR LOWER(COALESCE(company_name, '')) LIKE ?)"
        )
        params.extend([comp_upper, company.strip(), comp_like])
    if date and date.strip():
        clauses.append("substr(created_at, 1, 10) = ?")
        params.append(date.strip()[:10])
    if date_from and date_from.strip():
        clauses.append("substr(created_at, 1, 10) >= ?")
        params.append(date_from.strip()[:10])
    if date_to and date_to.strip():
        clauses.append("substr(created_at, 1, 10) <= ?")
        params.append(date_to.strip()[:10])
    if decision and decision.strip():
        dec_key = decision.strip().upper()
        aliases = _DECISION_FILTER_ALIASES.get(dec_key, (dec_key,))
        placeholders = ", ".join("?" for _ in aliases)
        clauses.append(f"(UPPER(COALESCE(decision, '')) IN ({placeholders}) OR UPPER(event_type) IN ({placeholders}))")
        params.extend([*aliases, *aliases])
    if metric_name and metric_name.strip():
        clauses.append("LOWER(COALESCE(metric_name, '')) = ?")
        params.append(metric_name.strip().lower())
    if event_type and event_type.strip():
        clauses.append("event_type = ?")
        params.append(event_type.strip())
    if actor and actor.strip():
        clauses.append("(actor = ? OR reviewer_id = ?)")
        params.extend([actor.strip(), actor.strip()])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _query_all(
        f"""
        SELECT event_id, seq_id, run_id, cik, ticker, company_name,
               filing_id, accession_number, metric_id, metric_name,
               event_type, decision, original_value, corrected_value,
               actor, reviewer_id, session_id, explanation,
               payload_json, prev_hash, event_hash, hash_version, created_at
        FROM audit_events
        {where_sql}
        ORDER BY event_id DESC
        LIMIT ?
        """,
        tuple(params),
        db_path=db_path,
    )


def save_filing_metadata(
    *,
    cik: str,
    ticker: str | None,
    company_name: str | None,
    accession_number: str,
    form_type: str,
    filing_date: str,
    reporting_period: str | None,
    fiscal_year: int | None = None,
    retrieval_status: str = "RETRIEVED",
    primary_document: str | None,
    filing_url: str,
    submissions_url: str,
    companyfacts_url: str,
    fetched_at: str,
    db_path: Path | str | None = None,
) -> int:
    """Insert or update SEC filing metadata in SQLite and return the row id."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sec_filings (
                cik, ticker, company_name, accession_number, form_type,
                filing_date, reporting_period, fiscal_year, retrieval_status,
                primary_document, filing_url, submissions_url, companyfacts_url, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, accession_number) DO UPDATE SET
                ticker = excluded.ticker,
                company_name = excluded.company_name,
                form_type = excluded.form_type,
                filing_date = excluded.filing_date,
                reporting_period = excluded.reporting_period,
                fiscal_year = excluded.fiscal_year,
                retrieval_status = excluded.retrieval_status,
                primary_document = excluded.primary_document,
                filing_url = excluded.filing_url,
                submissions_url = excluded.submissions_url,
                companyfacts_url = excluded.companyfacts_url,
                fetched_at = excluded.fetched_at
            """,
            (
                cik,
                ticker,
                company_name,
                accession_number,
                form_type,
                filing_date,
                reporting_period,
                fiscal_year,
                retrieval_status,
                primary_document,
                filing_url,
                submissions_url,
                companyfacts_url,
                fetched_at,
            ),
        )
        row = conn.execute(
            "SELECT id FROM sec_filings WHERE cik = ? AND accession_number = ?",
            (cik, accession_number),
        ).fetchone()
        return int(row["id"])


def fetch_filing_metadata(
    cik: str | None = None,
    form_type: str | None = None,
    db_path: Path | str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return stored SEC filing metadata records ordered by filing_date descending."""
    clauses: list[str] = []
    params: list[Any] = []
    if cik:
        clauses.append("cik = ?")
        params.append(cik)
    if form_type:
        clauses.append("form_type = ?")
        params.append(form_type)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _query_all(
        f"""
        SELECT id, cik, ticker, company_name, accession_number, form_type,
               filing_date, reporting_period, fiscal_year, retrieval_status,
               primary_document, filing_url, submissions_url, companyfacts_url, fetched_at
        FROM sec_filings
        {where_sql}
        ORDER BY filing_date DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
        db_path=db_path,
    )
