"""Append-only, tamper-evident audit event logging with sequential SHA-256 hash chaining.

Security model:
    FinovaLabs stores an append-only ledger using a monotonic sequential record identifier
    (``seq_id``) and cryptographic SHA-256 chaining (``prev_hash`` -> ``event_hash``).
    This makes the ledger **tamper-evident**—post-hoc edits, deletions, or reordering of
    existing rows break the chain during verification—but **not absolutely tamper-proof**
    against an adversary with direct write access to SQLite who alters records and
    recomputes every subsequent hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finova_labs.database import get_connection
from finova_labs.exceptions import AuditChainError
from finova_labs.logging_config import get_logger

logger = get_logger("audit")

GENESIS_HASH = "0" * 64
LATEST_HASH_VERSION = 2

TAMPER_EVIDENT_NOTICE = (
    "Tamper-Evident Ledger (Not Absolutely Tamper-Proof): Every record is linked via a "
    "monotonic sequential record ID (seq_id) and SHA-256 hash chain so post-hoc edits, "
    "deletions, or reordering are detected on verification. However, local SQLite storage "
    "is not immune to an adversary with direct database file write access recomputing hashes."
)

_PROCESS_SESSION_ID = os.environ.get("FINOVA_SESSION_ID") or f"session-{uuid.uuid4().hex[:12]}"


def get_default_session_id() -> str:
    """Return the active process/session identity used when callers do not supply one."""
    return _PROCESS_SESSION_ID


def compute_event_hash(
    prev_hash: str,
    run_id: str | None,
    event_type: str,
    actor: str,
    payload_json: str,
    created_at: str,
    *,
    seq_id: int | None = None,
    cik: str | None = None,
    ticker: str | None = None,
    company_name: str | None = None,
    filing_id: int | None = None,
    accession_number: str | None = None,
    metric_id: int | None = None,
    metric_name: str | None = None,
    decision: str | None = None,
    original_value: str | None = None,
    corrected_value: str | None = None,
    reviewer_id: str | None = None,
    session_id: str | None = None,
    explanation: str | None = None,
    hash_version: int = LATEST_HASH_VERSION,
) -> str:
    """Compute a deterministic SHA-256 digest linking an audit event to its predecessor."""
    if hash_version == 1:
        canonical_obj: dict[str, Any] = {
            "prev_hash": prev_hash,
            "run_id": run_id or "",
            "event_type": event_type,
            "actor": actor,
            "payload_json": payload_json,
            "created_at": created_at,
        }
    else:
        canonical_obj = {
            "hash_version": hash_version,
            "seq_id": seq_id,
            "prev_hash": prev_hash,
            "run_id": run_id or "",
            "cik": cik or "",
            "ticker": ticker or "",
            "company_name": company_name or "",
            "filing_id": filing_id,
            "accession_number": accession_number or "",
            "metric_id": metric_id,
            "metric_name": metric_name or "",
            "event_type": event_type,
            "decision": decision or "",
            "original_value": original_value,
            "corrected_value": corrected_value,
            "actor": actor,
            "reviewer_id": reviewer_id or "",
            "session_id": session_id or "",
            "explanation": explanation or "",
            "payload_json": payload_json,
            "created_at": created_at,
        }
    canonical = json.dumps(canonical_obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_str(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def _extract_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _insert_audit_row(
    conn: sqlite3.Connection,
    *,
    run_id: str | None,
    cik: str | None,
    ticker: str | None,
    company_name: str | None,
    filing_id: int | None,
    accession_number: str | None,
    metric_id: int | None,
    metric_name: str | None,
    event_type: str,
    decision: str | None,
    original_value: str | None,
    corrected_value: str | None,
    actor: str,
    reviewer_id: str,
    session_id: str,
    explanation: str | None,
    payload_json: str,
    created_at: str,
) -> int:
    last_row = conn.execute(
        "SELECT event_hash FROM audit_events ORDER BY event_id DESC LIMIT 1"
    ).fetchone()
    max_seq_row = conn.execute(
        "SELECT COALESCE(MAX(seq_id), COUNT(*)) AS last_seq FROM audit_events"
    ).fetchone()
    next_seq = (int(max_seq_row["last_seq"]) if max_seq_row else 0) + 1
    prev_hash = last_row["event_hash"] if last_row else GENESIS_HASH
    event_hash = compute_event_hash(
        prev_hash=prev_hash,
        run_id=run_id,
        event_type=event_type,
        actor=actor,
        payload_json=payload_json,
        created_at=created_at,
        seq_id=next_seq,
        cik=cik,
        ticker=ticker,
        company_name=company_name,
        filing_id=filing_id,
        accession_number=accession_number,
        metric_id=metric_id,
        metric_name=metric_name,
        decision=decision,
        original_value=original_value,
        corrected_value=corrected_value,
        reviewer_id=reviewer_id,
        session_id=session_id,
        explanation=explanation,
        hash_version=LATEST_HASH_VERSION,
    )
    cursor = conn.execute(
        """
        INSERT INTO audit_events (
            seq_id, run_id, cik, ticker, company_name, filing_id, accession_number,
            metric_id, metric_name, event_type, decision, original_value, corrected_value,
            actor, reviewer_id, session_id, explanation, payload_json,
            prev_hash, event_hash, hash_version, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            next_seq,
            run_id,
            cik,
            ticker,
            company_name,
            filing_id,
            accession_number,
            metric_id,
            metric_name,
            event_type,
            decision,
            original_value,
            corrected_value,
            actor,
            reviewer_id,
            session_id,
            explanation,
            payload_json,
            prev_hash,
            event_hash,
            LATEST_HASH_VERSION,
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def record_audit_event(
    event_type: str,
    actor: str = "system",
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
    db_path: Path | str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    cik: str | None = None,
    ticker: str | None = None,
    company_name: str | None = None,
    filing_id: int | None = None,
    accession_number: str | None = None,
    metric_id: int | None = None,
    metric_name: str | None = None,
    decision: str | None = None,
    original_value: Any = None,
    corrected_value: Any = None,
    reviewer_id: str | None = None,
    session_id: str | None = None,
    explanation: str | None = None,
    created_at: str | None = None,
) -> int:
    """Append a sequential, hash-chained audit event into SQLite and return its event_id.

    Pass ``conn`` to participate atomically inside an open SQLite transaction so domain
    decisions and their audit record commit or roll back together.
    """
    if not event_type or not event_type.strip():
        raise AuditChainError("event_type must not be empty.")

    payload_dict = dict(payload or {})
    clean_event_type = event_type.strip()
    clean_actor = (actor or "system").strip() or "system"
    clean_reviewer = _extract_str(reviewer_id) or _extract_str(payload_dict.get("reviewer_id")) or clean_actor
    clean_session = _extract_str(session_id) or _extract_str(payload_dict.get("session_id")) or get_default_session_id()

    resolved_cik = _extract_str(cik) or _extract_str(payload_dict.get("cik"))
    resolved_ticker = _extract_str(ticker) or _extract_str(payload_dict.get("ticker"))
    resolved_company = _extract_str(company_name) or _extract_str(payload_dict.get("company_name"))
    resolved_filing_id = filing_id if filing_id is not None else _extract_int(payload_dict.get("filing_id"))
    resolved_accn = _extract_str(accession_number) or _extract_str(payload_dict.get("accession_number"))
    resolved_metric_id = metric_id if metric_id is not None else _extract_int(payload_dict.get("metric_id"))
    resolved_metric_name = _extract_str(metric_name) or _extract_str(payload_dict.get("metric_name"))
    resolved_decision = (
        _extract_str(decision)
        or _extract_str(payload_dict.get("decision"))
        or _extract_str(payload_dict.get("status"))
        or _extract_str(payload_dict.get("action"))
        or clean_event_type
    )

    raw_orig = original_value if original_value is not None else payload_dict.get("original_value")
    if raw_orig is None:
        raw_orig = payload_dict.get("original_decimal")
    resolved_orig = str(raw_orig) if raw_orig is not None else None

    raw_corr = corrected_value if corrected_value is not None else payload_dict.get("corrected_value")
    if raw_corr is None:
        raw_corr = payload_dict.get("corrected_decimal")
    resolved_corr = str(raw_corr) if raw_corr is not None else None

    resolved_explanation = (
        _extract_str(explanation)
        or _extract_str(payload_dict.get("explanation"))
        or _extract_str(payload_dict.get("reviewer_note"))
        or _extract_str(payload_dict.get("reason"))
    )

    resolved_created_at = _extract_str(created_at) or datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"), default=str)

    if conn is not None:
        event_id = _insert_audit_row(
            conn,
            run_id=run_id,
            cik=resolved_cik,
            ticker=resolved_ticker,
            company_name=resolved_company,
            filing_id=resolved_filing_id,
            accession_number=resolved_accn,
            metric_id=resolved_metric_id,
            metric_name=resolved_metric_name,
            event_type=clean_event_type,
            decision=resolved_decision,
            original_value=resolved_orig,
            corrected_value=resolved_corr,
            actor=clean_actor,
            reviewer_id=clean_reviewer,
            session_id=clean_session,
            explanation=resolved_explanation,
            payload_json=payload_json,
            created_at=resolved_created_at,
        )
    else:
        with get_connection(db_path) as active_conn:
            event_id = _insert_audit_row(
                active_conn,
                run_id=run_id,
                cik=resolved_cik,
                ticker=resolved_ticker,
                company_name=resolved_company,
                filing_id=resolved_filing_id,
                accession_number=resolved_accn,
                metric_id=resolved_metric_id,
                metric_name=resolved_metric_name,
                event_type=clean_event_type,
                decision=resolved_decision,
                original_value=resolved_orig,
                corrected_value=resolved_corr,
                actor=clean_actor,
                reviewer_id=clean_reviewer,
                session_id=clean_session,
                explanation=resolved_explanation,
                payload_json=payload_json,
                created_at=resolved_created_at,
            )

    logger.info("Recorded audit event #%s (%s)", event_id, clean_event_type)
    return event_id


def verify_audit_chain(db_path: Path | str | None = None) -> tuple[bool, int, str | None]:
    """Verify sequential continuity and SHA-256 integrity of all audit_events rows.

    Returns ``(is_valid, total_events, failure_reason)``.
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, seq_id, run_id, cik, ticker, company_name,
                   filing_id, accession_number, metric_id, metric_name,
                   event_type, decision, original_value, corrected_value,
                   actor, reviewer_id, session_id, explanation, payload_json,
                   prev_hash, event_hash, hash_version, created_at
            FROM audit_events
            ORDER BY event_id ASC
            """
        ).fetchall()

    expected_prev = GENESIS_HASH
    expected_seq = 1
    for row in rows:
        hash_version = int(row["hash_version"] or 1)
        row_seq = row["seq_id"]
        if (hash_version >= 2 and row_seq != expected_seq) or (
            hash_version == 1 and row_seq is not None and row_seq != expected_seq
        ):
            msg = (
                f"Sequential record mismatch at event_id={row['event_id']} "
                f"(expected seq_id={expected_seq}, got {row_seq})"
            )
            logger.warning(msg)
            return False, len(rows), msg

        if row["prev_hash"] != expected_prev:
            msg = f"Broken prev_hash link at event_id={row['event_id']}"
            logger.warning(msg)
            return False, len(rows), msg

        expected_hash = compute_event_hash(
            prev_hash=row["prev_hash"],
            run_id=row["run_id"],
            event_type=row["event_type"],
            actor=row["actor"],
            payload_json=row["payload_json"],
            created_at=row["created_at"],
            seq_id=row_seq,
            cik=row["cik"],
            ticker=row["ticker"],
            company_name=row["company_name"],
            filing_id=row["filing_id"],
            accession_number=row["accession_number"],
            metric_id=row["metric_id"],
            metric_name=row["metric_name"],
            decision=row["decision"],
            original_value=row["original_value"],
            corrected_value=row["corrected_value"],
            reviewer_id=row["reviewer_id"],
            session_id=row["session_id"],
            explanation=row["explanation"],
            hash_version=hash_version,
        )
        if row["event_hash"] != expected_hash:
            msg = f"Hash mismatch detected at event_id={row['event_id']}"
            logger.warning(msg)
            return False, len(rows), msg

        expected_prev = row["event_hash"]
        expected_seq += 1

    return True, len(rows), None


def get_audit_chain_status(db_path: Path | str | None = None) -> dict[str, Any]:
    """Return tamper-evident verification metadata along with latest sequence & hash tip."""
    is_valid, count, failure_reason = verify_audit_chain(db_path=db_path)
    latest_seq: int | None = None
    latest_hash: str | None = None
    if count > 0:
        with get_connection(db_path) as conn:
            tip = conn.execute(
                "SELECT seq_id, event_id, event_hash FROM audit_events ORDER BY event_id DESC LIMIT 1"
            ).fetchone()
            if tip:
                latest_seq = int(tip["seq_id"] or tip["event_id"])
                latest_hash = tip["event_hash"]
    return {
        "is_valid": is_valid,
        "total_events": count,
        "latest_seq_id": latest_seq,
        "latest_event_hash": latest_hash,
        "failure_reason": failure_reason,
        "tamper_model": "tamper-evident",
        "tamper_notice": TAMPER_EVIDENT_NOTICE,
    }
