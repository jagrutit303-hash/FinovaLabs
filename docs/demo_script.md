# FinovaLabs — Five-Minute Hackathon Judging Demo Script

**Product:** FinovaLabs — *AI-Powered Financial Filing Auditor*  
**Format:** Live 5-minute demonstration using real SEC EDGAR data (zero fabricated numbers)

---

## Pre-Demo Check (30 seconds before judging)

1. Confirm `.env` exists in `c:\Users\Jagruti\FinovaLabs\.env` with a valid contact email:
   `FINOVALABS_SEC_CONTACT_EMAIL=<your-real-email>`
2. Optional clean start if you want the judge to watch from an empty SQLite database:
   ```powershell
   Remove-Item data\finova_labs.db -ErrorAction SilentlyContinue
   ```
   *(Keep `data\cache\sec\` intact so live demo runs avoid SEC rate-limit latency while still using genuine SEC EDGAR submissions, Company Facts JSON, and 10-K Inline XBRL HTML; check **"Refresh from SEC"** only if demonstrating a live download.)*
3. Launch FinovaLabs:
   ```powershell
   cd c:\Users\Jagruti\FinovaLabs
   .venv\Scripts\Activate.ps1
   streamlit run app.py
   ```

---

## Timed 5-Minute Live Demo Flow

### 0:00 – 0:35 | Act 1 — Honest Empty Foundation & Architecture (`Overview`)
- **Open:** **Overview** (default page).
- **Point out:**
  - Deep-navy enterprise sidebar with 5 pages (`Overview`, `Filing Analysis`, `Human Review`, `Accuracy Report`, `Audit Trail`).
  - With a fresh DB, all KPI cards read `0` / `—` and tables show explicit empty states ("No SEC 10-K filings retrieved yet", "No filing audit runs recorded yet") — **zero synthetic placeholder metrics**.
  - Click **Verify DB Health** -> confirms SQLite is initialized with all **8 core tables** (`audit_runs`, `sec_filings`, `extracted_metrics`, `review_tasks`, `validation_results`, `accuracy_evaluations`, `audit_events`, `idempotency_records`).

---

### 0:35 – 1:45 | Act 2 — Real Company Selection, SEC 10-K Retrieval & Dual-Path Extraction (`Filing Analysis`)
- **Navigate to:** **Filing Analysis**.
- **Select companies:** In the multiselect, select **Microsoft (MSFT)** and **Amazon (AMZN)** *(optionally uncheck others so extraction is fast and contrast is clear)*.
- **Click:** **Retrieve Latest 10-K Filings**.
  - Show dynamic CIK resolution (`0000789019` for Microsoft, `0001018724` for Amazon), real SEC filing dates, fiscal years, accession numbers, and `RETRIEVED` status persisted to SQLite.
- **Extract & Validate MSFT (the clean 8/8 auto-approved baseline):**
  1. In **Filter by Company**, choose `MSFT`.
  2. Keep **Parse 10-K HTML Inline XBRL for original scale & table evidence** checked.
  3. Click **Extract 8 Core Financial Metrics**.
  4. Show the status banner: `Workflow ... COMPLETED: 8 metric(s) auto-approved`.
  5. Show the **Extracted Financial Metrics (SQLite)** table:
     - All 8 metrics extracted (`Revenue`, `Net Income`, `Total Assets`, `Total Liabilities`, `Shareholders' Equity`, `Operating Cash Flow`, `Cash and Cash Equivalents`, `Earnings Per Share`).
     - Exact reported units (`USD`, `USD/shares`), scale factors (`1,000,000x` vs `1x`), annual periods (`FY 2026`), and confidence scores (`98.8%`–`100.0%`).
  6. Expand **Traceable Source Evidence, Confidence Breakdown & Candidate Facts**:
     - Show table/row evidence location (`10-K HTML Table #..., Row #...`), verbatim snippet, SEC filing URL, and the **5-factor breakdown** (`Label/Concept 25%`, `Period 25%`, `Unit/Scale 20%`, `Evidence 20%`, `Independent-Path 10%`).
  7. Scroll to **Financial Validation Engine Results (SQLite)**:
     - Show `accounting_equation` (`PASS`), `segment_revenue` (`PASS` — 3 Microsoft segments reconcile to consolidated revenue within ±2%), and `yoy_comparison` (`PASS` and `WARNING` for >30% YoY changes).

---

### 1:45 – 2:55 | Act 3 — Real Low-Confidence Human Escalation & Saved Workflow Recovery (`Filing Analysis` -> Restart -> `Overview`)
- **Still in `Filing Analysis`:**
  1. Switch **Filter by Company** to `AMZN`.
  2. Click **Extract 8 Core Financial Metrics**.
  3. Show what happens on real SEC data: **`Workflow ... PAUSED for Human Review: 7 auto-approved, 1 task(s) escalated.`**
  4. Explain *why* honestly (no staged failure needed):
     - Amazon (`AMZN`, like Walmart `WMT`) reports current liabilities, noncurrent liabilities, and `LiabilitiesAndStockholdersEquity` in its 10-K XBRL, **without tagging a standalone `us-gaap:Liabilities` subtotal**.
     - FinovaLabs refuses to invent `Total Liabilities`: it marks it `MISSING`, gives `Confidence = 0.0%`, marks `Accounting Equation (A = L + E)` and `Total Liabilities` YoY as **`NOT_APPLICABLE`** (never `PASS`), and pauses the **LangGraph SQLite checkpoint** (`PAUSED_FOR_REVIEW`).
- **Demonstrate Real Crash/Restart Recovery:**
  1. In the terminal, press **`Ctrl+C`** to stop the running Streamlit server completely while `AMZN` is paused mid-workflow.
  2. Relaunch `streamlit run app.py`.
  3. On **Overview**, point out **"Interrupted & Pending Workflows (Restart Recovery)"**:
     - The paused `AMZN` workflow, its 7 auto-approved metrics, validation results, and 1 open human review task are all intact in SQLite without re-running extraction or duplicating records.
     - Point out the caption noting that `Resume Workflow` unlocks as soon as open Human Review task(s) are resolved (or immediately for `INTERRUPTED` runs with `0` open tasks).

---

### 2:55 – 3:45 | Act 4 — Mandatory Human-in-the-Loop Decision (`Human Review`)
- **Navigate to:** **Human Review**.
- Show the open task card for `Amazon.com, Inc. (AMZN) • Total Liabilities`:
  - Company, Metric, Original Extracted Value (`—`), Period (`FY 2025`), Unit (`USD`), Confidence (`0.0%` vs Threshold `90.0%`), Source Filing accession & URL, and **Reason for Escalation**.
- **Verify mandatory explanation guard:**
  - Click **Reject** (or **Correct Value**) *before* typing an explanation -> FinovaLabs blocks the submission with a clear validation error banner.
- **Submit real human decision:**
  - Option A (**Reject — purest zero-fabrication choice**): Enter `Reviewer Name` (e.g., `lead.auditor`), enter explanation `"Verified AMZN 10-K Balance Sheet reports current/noncurrent liabilities without a separate Total Liabilities XBRL concept; keeping un-tagged subtotal rejected per zero-fabrication policy."`, and click **Reject**.
  - Option B (**Correct Value — demonstrate edit + original preservation**): If demonstrating numerical correction, check the sum of Current + Noncurrent liabilities from Amazon's 10-K Balance Sheet (`total assets - stockholders' equity` from the filing), enter it in **Editable Correction Value**, write the exact filing-table derivation in the justification box, and click **Correct Value**.
- Show immediate result:
  - SQLite commits the human decision and append-only audit record **atomically before resuming** the LangGraph checkpoint, transitioning the `AMZN` run from `PAUSED_FOR_REVIEW` to `COMPLETED_WITH_REJECTIONS` (for Reject) or `COMPLETED` (for Correct/Approve).

---

### 3:45 – 4:30 | Act 5 — SEC Company Facts Accuracy Comparison (`Accuracy Report`)
- **Navigate to:** **Accuracy Report**.
- **Click:** **Evaluate vs. SEC Facts** (with `All Audit Runs` selected).
- **Point out the core evaluation guarantees:**
  - **Separate Pre-Review vs. Post-Review Accuracy:** Human edits never mask raw extraction performance.
  - **Explicit Denominators & Ground-Truth Coverage:**
    - `MSFT`: `100.0%` pre-review accuracy (`8/8` verifiable), `100.0%` ground-truth coverage.
    - `AMZN`: `100.0%` pre-review accuracy on verifiable facts (`7/7`), `87.5%` ground-truth coverage (`Total Liabilities` reported cleanly as `UNAVAILABLE_REFERENCE` — **never counted as a match**).
  - Show Company Breakdown & Metric Breakdown Plotly charts and click **Download FinovaLabs Accuracy CSV** / **JSON** to show branded exports.

---

### 4:30 – 5:00 | Act 6 — Append-Only Tamper-Evident Audit Trail (`Audit Trail`)
- **Navigate to:** **Audit Trail**.
- Show **Reviewer Decisions (Append-Only Decision History)** with `Seq #`, `Timestamp (UTC)`, `Reviewer / Session`, `Workflow ID`, `Company / Filing`, `Metric`, `Decision`, `Original Value`, `Corrected Value`, and `Explanation`.
- Filter using **Company** (`AMZN`), **Date (UTC)**, **Decision**, and **Metric** (`Total Liabilities`).
- Click **Re-Verify Audit Hash Chain** -> confirms SHA-256 chain continuity across all events (`seq_id` + `prev_hash` + `event_hash`).
- **Close honestly:** Highlight the info banner explaining that this SHA-256 hash chain is **tamper-evident** (any edit/deletion to historical rows breaks verification immediately), **not absolutely tamper-proof** against a host administrator who rewrites the SQLite file and recomputes every hash offline.

---

## Known Limitations to State Honestly During Judging

1. **5 Curated Large-Cap US Tickers in UI:** Only `AAPL`, `MSFT`, `GOOGL`, `AMZN`, and `WMT` are selectable in the UI dropdown (`filing_manager.py`), though CIKs are resolved dynamically from SEC EDGAR rather than hardcoded.
2. **Annual 10-K Focus:** Extraction, period normalization, and validation target annual Form `10-K` / `10-K/A` filings (`~330–385` day durations and fiscal-year-end instants); quarterly `10-Q` workflows are outside scope.
3. **Real SEC XBRL Tagging Variance (`AMZN` & `WMT` Liabilities):** Companies that do not tag `us-gaap:Liabilities` explicitly trigger legitimate `MISSING` escalations rather than hidden arithmetic derivation.
4. **Single-User SQLite Governance:** Reviewer identity uses a text field + browser session ID (`ui-<hex>`) without enterprise SSO/RBAC; audit protection is single-database **tamper-evident**, not multi-party **tamper-proof**.
5. **Legacy `pages/` Directory:** [pages/](file:///c:/Users/Jagruti/FinovaLabs/pages/1_Run_Overview.py) preserves Milestone-1 filenames for backward compatibility; the canonical 5-page app runs via `streamlit run app.py`.
