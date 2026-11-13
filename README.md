# FinovaLabs

**AI-Powered Financial Filing Auditor** (`MINEARENA PS-01`)

FinovaLabs is a Python, Streamlit, LangGraph, and SQLite auditing platform for real SEC EDGAR Form `10-K` financial metric extraction, Decimal normalization, 5-factor explainable confidence scoring, financial rule validation, mandatory human-in-the-loop review with crash recovery, SEC Company Facts accuracy benchmarking, and tamper-evident append-only audit logging.

---

## Windows Setup & Installation

### 1. Prerequisites
- **Windows 10/11** with **Python 3.11+** installed (`python --version`)
- Internet access to `data.sec.gov` and `www.sec.gov` (after initial run, cached SEC JSON/HTML responses reside in `data/cache/sec/`)

### 2. Create & Activate Virtual Environment (PowerShell)
```powershell
cd C:\Users\Jagruti\FinovaLabs
python -m venv .venv
.venv\Scripts\Activate.ps1
```
*(If PowerShell blocks script execution, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and re-run `Activate.ps1`.)*

### 3. Install Dependencies
```powershell
# Python backend dependencies
pip install -r requirements.txt

# React frontend dependencies (works from repository root or inside frontend/)
npm install
```

### 4. Environment & Threshold Configuration
1. Copy `.env.example` to `.env` in the repository root:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Edit `.env` and set a **real email address** (required by SEC EDGAR Fair Access policy — placeholder emails are rejected):
   ```dotenv
   FINOVALABS_SEC_CONTACT_EMAIL=your.name@yourdomain.com
   ```
   *(Optional override: `FINOVALABS_SEC_USER_AGENT="FinovaLabs your.name@yourdomain.com"`)*
3. Thresholds, SEC rate limits, database path, and log paths live in [config.yaml](config.yaml) (defaults: `auto_approve_threshold: 0.90`, `yoy_change_alert_threshold: 0.30`, `accounting_identity_tolerance: 0.0005`, `segment_reconciliation_tolerance: 0.02`).

### 5. Launch the Application

**Terminal 1 — FastAPI Backend Engine**:
```powershell
cd C:\Users\Jagruti\FinovaLabs
$env:PYTHONPATH="src"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — React User Interface**:
```powershell
cd C:\Users\Jagruti\FinovaLabs
npm run dev
```
Navigate to [http://localhost:5173/](http://localhost:5173/) to access the full auditing workspace:
1. **Landing Page** (`/`) — Premium Originkit Hero 66 product introduction
2. **Operational Overview** (`/app`) — SQLite status, active filings, and interrupted workflow recovery
3. **New Audit** (`/app/audits/new`) — 3-step company search, filing selection, and LangGraph pipeline launch
4. **Audit Workspace** (`/app/audits/:auditId`) — Normalized metrics, 5-factor confidence scoring, and evidence
5. **Financial Analytics** (`/app/analytics`) — Performance time-series, YoY variance anomalies, and balance equation
6. **Review Center** (`/app/reviews`) — Governed approval, correction, and rejection with audit trail commit
7. **Reports & Ledger** (`/app/reports`) — Ground-truth accuracy benchmarks and tamper-evident SHA-256 chain

*(Optional legacy Streamlit view: `streamlit run app.py` on port 8501)*

---

## Test Commands

Run the full automated suite from `C:\Users\Jagruti\FinovaLabs` (currently **53 tests**):
```powershell
pytest -vv -rs
```

Run offline unit/integration suites only (skipping live `sec.gov` network tests):
```powershell
pytest -v -k "not live"
```

Run live SEC EDGAR verification tests only (requires `.env` contact email + network/cache):
```powershell
pytest -v tests/test_sec_live.py tests/test_extraction_live.py
```

Run dependency consistency check:
```powershell
python -m pip check
```

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Windows PowerShell default policy | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then `.venv\Scripts\Activate.ps1`. |
| `ConfigurationError: placeholder SEC email` or `SEC EDGAR HTTP 403` | `.env` missing or contains `contact@example.com` | Set a real address in `.env`: `FINOVALABS_SEC_CONTACT_EMAIL=you@domain.com`. |
| `ModuleNotFoundError: No module named 'finova_labs'` | Running Python outside repo root without `src/` on `sys.path` | Run commands from `C:\Users\Jagruti\FinovaLabs` or use `streamlit run app.py` / `pytest`. |
| Port `8501` already in use | Existing Streamlit process running | Launch on another port: `streamlit run app.py --server.port 8502`. |
| `No LangGraph SQLite checkpoint found` on `Resume Workflow` | Run was manually inserted into SQLite without `start_audit_workflow` | Start runs via the **Filing Analysis** UI or `start_audit_workflow(...)` so `SqliteSaver` writes its checkpoint. |
| Want a clean DB before demo | Prior runs stored in `data/finova_labs.db` | Stop Streamlit (`Ctrl+C`), run `Remove-Item data\finova_labs.db`, and relaunch `streamlit run app.py`. |

---

## Project Architecture & Files

- `app.py` — Streamlit `st.navigation` router (5 views) & startup initializer
- `config.yaml` / `.env` — Typed Pydantic settings & SEC EDGAR User-Agent contact configuration
- `src/finova_labs/`:
  - `sec_client.py`, `filing_manager.py`, `filing_parser.py` — Rate-limited cached SEC client, 5-company orchestration, Inline XBRL + HTML table parser
  - `metric_mapping.py`, `extractor.py`, `normalization.py` — 8 approved metrics, dual-path extraction, `Decimal` unit/scale/period normalization
  - `confidence.py` — 5-factor explainable scoring (`0.25 / 0.25 / 0.20 / 0.20 / 0.10`), explicit `UNAVAILABLE` factor handling, `0.90` threshold
  - `validators.py` — Accounting equation (`A = L + E`), segment revenue reconciliation, and YoY anomaly engine (`PASS`, `WARNING`, `FAIL`, `NOT_APPLICABLE`)
  - `workflow.py`, `database.py` — LangGraph + `SqliteSaver` HITL interrupt/resume state machine, idempotency keys, and 8-table SQLite persistence
  - `evaluation.py`, `reporting.py` — Pre/post-review SEC Company Facts accuracy comparator & CSV/JSON exports
  - `audit.py` — Append-only `seq_id` + `SHA-256` hash-chained ledger (`verify_audit_chain`)
  - `ui.py`, `views.py`, `exceptions.py`, `logging_config.py` — Navy/white enterprise theme, Plotly charts, interactive UI views, rotating logs
- `docs/` — [Demo Script](docs/demo_script.md), [Architecture](docs/architecture.md), [Metric Mapping](docs/metric_mapping.md)
- `pages/` — Legacy 4 Milestone-1 standalone wrapper scripts kept for compatibility (`app.py` serves the canonical 5 views)
- `tests/` — 15 pytest modules covering every subsystem

---

## Honest Scope & Limitations

- **Supported Companies**: UI dropdown supports 5 curated US large-cap equities (`AAPL`, `MSFT`, `GOOGL`, `AMZN`, `WMT`), dynamically resolved to CIKs via SEC EDGAR; arbitrary ticker search and foreign private issuers (`20-F`/`40-F`) are not exposed in the UI.
- **Form Coverage**: Annual Form `10-K` / `10-K/A` filings only; quarterly `10-Q` extraction is not enabled in the workflow.
- **SEC XBRL Tagging Gaps (`AMZN`, `WMT`)**: When an issuer omits a standalone `us-gaap:Liabilities` subtotal tag in SEC Company Facts, FinovaLabs refuses to fabricate the number, escalates `Total Liabilities` (`MISSING`, confidence `0.0%`) to Human Review, marks Accounting Equation `NOT_APPLICABLE`, and excludes the missing reference from Company Facts match credit.
- **Audit Chain Model**: The SQLite `seq_id` + `SHA-256` chain in `audit.py` is **tamper-evident** (immediately detects row modification/deletion), **not absolutely tamper-proof** against a privileged host administrator rewriting the database and recomputing every hash offline.
- **Single-Node Governance**: Reviewer attribution captures Reviewer Name + per-browser session UUID (`ui-<hex>`) without enterprise SSO/RBAC.

---

## Final Problem-Statement Compliance Checklist

| Mandatory Requirement | Implemented Status | Primary Code / Verification |
| --- | --- | --- |
| Dynamic SEC EDGAR 10-K retrieval, caching & rate limiting | Verified | `sec_client.py`, `filing_manager.py`, `test_sec_client.py`, `test_sec_live.py` |
| 8-metric extraction with units, periods, scale & verbatim evidence | Verified | `metric_mapping.py`, `filing_parser.py`, `extractor.py`, `normalization.py`, `test_extraction_live.py` |
| 5-factor explainable confidence engine (`0–1`, `0.90` cutoff, explicit missing factors) | Verified | `confidence.py`, `test_confidence.py` |
| Financial validation engine (`A = L + E`, segments, YoY ±30%, 4 distinct statuses) | Verified | `validators.py`, `test_validators.py` |
| Mandatory HITL review (`APPROVE` / `EDIT` / `REJECT`, note enforcement, original preservation) | Verified | `workflow.py`, `views.py`, `test_review_workflow.py` |
| Durable SQLite persistence, LangGraph checkpoints, restart recovery & idempotency | Verified | `database.py`, `workflow.py`, `test_restart_recovery.py` |
| SEC Company Facts accuracy (pre vs. post review, coverage denominators, breakdowns) | Verified | `evaluation.py`, `reporting.py`, `test_evaluation.py` |
| Append-only tamper-evident audit trail (`seq_id`, SHA-256 hash chain, filters) | Verified | `audit.py`, `views.py`, `test_audit_log.py` |
| Polished 5-screen FinovaLabs Streamlit UI (`Overview` to `Audit Trail`) | Verified | `app.py`, `ui.py`, `views.py`, `test_frontend.py` |
| Judging script (`docs/demo_script.md`) with zero fabricated SEC results | Verified | [docs/demo_script.md](docs/demo_script.md) |
