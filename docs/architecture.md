# FinovaLabs Architecture

**AI-Powered Financial Filing Auditor (MINEARENA PS-01)**

FinovaLabs is a Python + Streamlit + LangGraph + SQLite application designed for verifiable, human-governed SEC Form `10-K` financial extraction and benchmarking.

---

## End-to-End Pipeline

1. **SEC EDGAR Ingestion & Caching (`sec_client.py`, `filing_manager.py`, `filing_parser.py`)**
   - Dynamically maps tickers (`AAPL`, `MSFT`, `GOOGL`, `AMZN`, `WMT`) via official SEC `company_tickers.json` to zero-padded 10-digit CIKs.
   - Rate-limited HTTP client (`<= max_requests_per_second`, exponential backoff retries, compliant `User-Agent` from `.env`) fetching Submissions JSON, XBRL Company Facts JSON, and primary `10-K` HTML.
   - All SEC payloads are disk-cached under `data/cache/sec/` and deduplicated in SQLite (`sec_filings`, `UNIQUE(cik, accession_number)`).
   - `filing_parser.py` parses Inline XBRL (`ix:nonFraction`, `context`, `unit`) and HTML tables while excluding dimensional breakdown contexts from consolidated metrics and capturing verbatim row snippets and `Table #X, Row #Y` locations.

2. **Extraction & Decimal Normalization (`metric_mapping.py`, `extractor.py`, `normalization.py`)**
   - Extracts **8 core annual metrics**: `Revenue`, `Net Income`, `Total Assets`, `Total Liabilities`, `Shareholders' Equity`, `Operating Cash Flow`, `Cash and Cash Equivalents`, and `Earnings Per Share`.
   - Exact `Decimal` arithmetic (`normalized_decimal` + `scale_factor` + `normalized_value`) handles parentheses/negative signs, `in millions` / `in thousands` / Inline XBRL `scale` powers, and annual (`330–385` days) vs. quarterly/YTD/instant separation.
   - Cross-references SEC Company Facts and 10-K HTML Inline XBRL cleanly; conflicting candidates are flagged `AMBIGUOUS` rather than silently guessing.

3. **Explainable Confidence Scoring (`confidence.py`)**
   - Computes `[0, 1]` score from 5 configurable factors (`config.yaml`):
     - `label_concept_match`: **25%**
     - `reporting_period_match`: **25%**
     - `unit_scale_correctness`: **20%**
     - `evidence_quality`: **20%**
     - `independent_path_agreement`: **10%**
   - Unavailable factors are marked `UNAVAILABLE` (`raw_score=None`, contribution `0.00`) and never treated as passing.
   - Metrics `< auto_approve_threshold` (default `0.90`) or status `!= EXTRACTED` escalate to human review.

4. **Financial Validation Engine (`validators.py`)**
   - **Accounting Equation**: `Total Assets = Total Liabilities + Shareholders' Equity` within `max(2 * max_scale_factor USD, abs(Assets) * accounting_identity_tolerance)`. Reports `NOT_APPLICABLE` if balance sheet inputs are missing.
   - **Segment Revenue Reconciliation**: Compares disclosed segment revenues against consolidated `Revenue` within `±2%` when comparable segments exist; reports `NOT_APPLICABLE` with explanation otherwise.
   - **Year-over-Year (YoY) Anomaly Check**: Compares annual metrics against prior FY (default `±30%` alert threshold), handling missing priors, fiscal-year-length shifts, negative-to-positive transitions, restatements, and non-comparable periods safely as `PASS`, `WARNING`, `FAIL`, or `NOT_APPLICABLE`.

5. **Durable Workflow, Crash Recovery & HITL (`workflow.py`, `database.py`)**
   - Built on `LangGraph` + `langgraph-checkpoint-sqlite` (`SqliteSaver`) sharing `data/finova_labs.db`.
   - Stages (`STARTED -> EXTRACTED -> SCORED -> VALIDATED -> HUMAN_REVIEW_WAIT -> COMPLETED / COMPLETED_WITH_REJECTIONS`) checkpoint state and enforce idempotency via `idempotency_records`.
   - Automatically approves **only** records that meet confidence threshold **and** pass all applicable validations.
   - Pauses via LangGraph `interrupt(...)` whenever confidence falls below threshold or a validation escalates; human `APPROVE`, `EDIT`, and `REJECT` decisions require explanations for edits/rejections, preserve `original_value` permanently, and commit atomically before resuming.

6. **SEC Company Facts Evaluation & Reporting (`evaluation.py`, `reporting.py`)**
   - Compares pre-review and post-review values separately against matching Company Facts entries (strict company, concept, `FY` period, unit, and accession checks; period/unit mismatches and missing ground truth never count as matches).
   - Computes raw accuracy, post-review accuracy, extraction coverage, ground-truth coverage, and exports FinovaLabs-branded CSV/JSON reports.

7. **Append-Only Tamper-Evident Audit Ledger (`audit.py`)**
   - Every extraction, validation, human review decision, amendment, workflow state transition, and accuracy evaluation appends to `audit_events` with sequential `seq_id`, `prev_hash`, and `event_hash` (`SHA-256`).
   - Provides cryptographic tamper detection (`verify_audit_chain()`), while clearly documenting its boundary as **tamper-evident** rather than absolutely tamper-proof on a single host.

8. **Multipage Frontend (`app.py`, `ui.py`, `views.py`)**
   - `app.py` routes 5 Streamlit pages via `st.navigation`:
     1. **Overview**
     2. **Filing Analysis**
     3. **Human Review**
     4. **Accuracy Report**
     5. **Audit Trail**

---

## SQLite Persistence Schema (`data/finova_labs.db`)

- **Application Core Tables (8)**: `audit_runs`, `sec_filings`, `extracted_metrics`, `review_tasks`, `validation_results`, `accuracy_evaluations`, `audit_events`, `idempotency_records`
- **LangGraph Checkpointer Tables**: initialized automatically in the same SQLite database via `SqliteSaver.setup()`
