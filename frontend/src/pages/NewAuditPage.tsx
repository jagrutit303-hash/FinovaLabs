import React, { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Play,
  RotateCcw,
  CheckCircle2,
  ShieldCheck,
  Search,
  ExternalLink,
  ArrowRight,
  AlertTriangle,
  FileCheck2,
} from 'lucide-react'
import { api } from '../api/client'
import type { Company, Filing, AuditRun } from '../api/client'

export const NewAuditPage: React.FC = () => {
  const navigate = useNavigate()

  // Search & Company selection states
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [companies, setCompanies] = useState<Company[]>([])
  const [loadingCompanies, setLoadingCompanies] = useState<boolean>(false)
  const [selectedTicker, setSelectedTicker] = useState<string>('AAPL')

  // Filing states
  const [filings, setFilings] = useState<Filing[]>([])
  const [selectedAccession, setSelectedAccession] = useState<string>('')
  const [loadingFilings, setLoadingFilings] = useState<boolean>(false)

  // Existing Audit Detection states
  const [existingAudits, setExistingAudits] = useState<AuditRun[]>([])
  const [forceReprocess, setForceReprocess] = useState<boolean>(false)

  // Submission & Progress states
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [activeStage, setActiveStage] = useState<number>(1)
  const [error, setError] = useState<string | null>(null)

  // 1. Fetch companies from backend (with optional search query)
  useEffect(() => {
    setLoadingCompanies(true)
    const timeout = setTimeout(() => {
      api.getCompanies(searchQuery.trim() || undefined)
        .then((data) => {
          setCompanies(data)
          if (data.length > 0 && !data.some((c) => c.ticker === selectedTicker)) {
            setSelectedTicker(data[0].ticker)
          }
        })
        .catch(() => {
          // Keep existing if backend transient error
        })
        .finally(() => setLoadingCompanies(false))
    }, 250)

    return () => clearTimeout(timeout)
  }, [searchQuery])

  // 2. Fetch existing audits for existing audit detection
  useEffect(() => {
    api.getAudits()
      .then(setExistingAudits)
      .catch(() => setExistingAudits([]))
  }, [])

  // 3. Fetch SEC Form 10-K filings for the selected company
  useEffect(() => {
    if (!selectedTicker) return
    setLoadingFilings(true)
    setError(null)

    api.getCompanyFilings(selectedTicker)
      .then((data) => {
        setFilings(data)
        if (data.length > 0) {
          setSelectedAccession(data[0].accession_number)
        } else {
          setSelectedAccession('')
        }
      })
      .catch(() => {
        setFilings([])
        setSelectedAccession('')
      })
      .finally(() => setLoadingFilings(false))
  }, [selectedTicker])

  // Detect if an audit already exists for this selected company / filing
  const existingAuditMatch = useMemo(() => {
    return existingAudits.find((a) => {
      if (a.ticker !== selectedTicker) return false
      if (selectedAccession && a.accession_number) {
        return a.accession_number === selectedAccession
      }
      return true
    })
  }, [existingAudits, selectedTicker, selectedAccession])

  // 4. Handle audit creation with animated progress steps
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedTicker) return

    setSubmitting(true)
    setActiveStage(1)
    setError(null)

    // Simulate clean visual stage progression while backend executes
    const stageTimer1 = setTimeout(() => setActiveStage(2), 600)
    const stageTimer2 = setTimeout(() => setActiveStage(3), 1400)
    const stageTimer3 = setTimeout(() => setActiveStage(4), 2200)

    try {
      const result = await api.createAudit({
        ticker: selectedTicker,
        accession_number: selectedAccession || undefined,
        force_reprocess: forceReprocess,
      })

      // Backend confirmed operation
      navigate(`/app/audits/${result.run_id}`)
    } catch (err: any) {
      clearTimeout(stageTimer1)
      clearTimeout(stageTimer2)
      clearTimeout(stageTimer3)
      setError(err.message || 'Audit execution encountered a backend error.')
      setSubmitting(false)
    }
  }

  const selectedCompany = companies.find((c) => c.ticker === selectedTicker)

  return (
    <div className="py-8 px-4 sm:px-6 lg:px-8 max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
          Initiate Financial Filing Audit
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Query SEC EDGAR for Form 10-K submissions, extract 8 standardized financial metrics with exact Decimal precision, and validate accounting identities.
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Audit initiation halted:</span> {error}
          </div>
        </div>
      )}

      {/* Progress State Overlay when submitting */}
      {submitting && (
        <div className="rounded-2xl border border-blue-200 bg-blue-50/70 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <RotateCcw className="h-5 w-5 text-blue-600 animate-spin" />
              <span className="text-sm font-semibold text-blue-950">
                Executing LangGraph Financial Audit Workflow...
              </span>
            </div>
            <span className="font-mono text-xs font-bold text-blue-700">
              Stage {activeStage} of 4
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 text-xs">
            <div className={`p-2.5 rounded-lg border ${activeStage >= 1 ? 'bg-white border-blue-300 font-semibold text-blue-900 shadow-xs' : 'bg-slate-100/50 border-slate-200 text-slate-400'}`}>
              1. SEC EDGAR Ingestion
            </div>
            <div className={`p-2.5 rounded-lg border ${activeStage >= 2 ? 'bg-white border-blue-300 font-semibold text-blue-900 shadow-xs' : 'bg-slate-100/50 border-slate-200 text-slate-400'}`}>
              2. Decimal Extraction
            </div>
            <div className={`p-2.5 rounded-lg border ${activeStage >= 3 ? 'bg-white border-blue-300 font-semibold text-blue-900 shadow-xs' : 'bg-slate-100/50 border-slate-200 text-slate-400'}`}>
              3. 5-Factor Scoring
            </div>
            <div className={`p-2.5 rounded-lg border ${activeStage >= 4 ? 'bg-white border-blue-300 font-semibold text-blue-900 shadow-xs' : 'bg-slate-100/50 border-slate-200 text-slate-400'}`}>
              4. Accounting Validation
            </div>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Step 1: Search & Select Company */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                1
              </span>
              <h2 className="text-base font-semibold text-slate-900">
                Search & Select US Equity
              </h2>
            </div>
            <span className="text-xs text-slate-500">Real SEC EDGAR entity lookup</span>
          </div>

          {/* Search Input */}
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by ticker or company name (e.g. AAPL, Microsoft, NVDA, AMZN)..."
              className="w-full rounded-lg border border-slate-300 pl-9 pr-4 py-2 text-xs text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            {loadingCompanies && (
              <RotateCcw className="absolute right-3 top-2.5 h-4 w-4 text-slate-400 animate-spin" />
            )}
          </div>

          {/* Companies Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pt-1">
            {companies.map((c) => {
              const selected = c.ticker === selectedTicker
              return (
                <div
                  key={c.ticker}
                  onClick={() => setSelectedTicker(c.ticker)}
                  className={`cursor-pointer rounded-xl border p-4 transition-all ${
                    selected
                      ? 'border-blue-600 bg-blue-50/50 ring-2 ring-blue-600/20'
                      : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-bold text-slate-900">{c.ticker}</span>
                    {selected && <CheckCircle2 className="h-4 w-4 text-blue-600" />}
                  </div>
                  <div className="mt-1 text-xs font-medium text-slate-700 truncate" title={c.company_name}>
                    {c.company_name}
                  </div>
                  <div className="mt-1 text-[11px] font-mono text-slate-400">
                    CIK: {c.cik || 'Resolving...'}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Step 2: Select 10-K Filing */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                2
              </span>
              <h2 className="text-base font-semibold text-slate-900">Select Form 10-K Filing</h2>
            </div>
            {selectedCompany && (
              <span className="text-xs font-mono text-slate-500">
                Selected: {selectedCompany.ticker}
              </span>
            )}
          </div>

          {loadingFilings ? (
            <div className="py-6 text-center text-xs text-slate-400">
              <RotateCcw className="h-4 w-4 text-blue-600 animate-spin inline-block mr-2" />
              Retrieving filings from SEC EDGAR...
            </div>
          ) : filings.length > 0 ? (
            <div className="space-y-2 pt-1">
              {filings.map((f) => {
                const selected = f.accession_number === selectedAccession
                return (
                  <div
                    key={f.accession_number}
                    onClick={() => setSelectedAccession(f.accession_number)}
                    className={`cursor-pointer rounded-lg border p-3 flex items-center justify-between transition-all ${
                      selected
                        ? 'border-blue-600 bg-blue-50/40 ring-1 ring-blue-600'
                        : 'border-slate-200 hover:border-slate-300'
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-slate-900">
                          Form {f.form_type}
                        </span>
                        {f.fiscal_year && (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-700">
                            FY{f.fiscal_year}
                          </span>
                        )}
                        <span className="text-xs text-slate-500">
                          Period: {f.reporting_period || f.filing_date}
                        </span>
                      </div>
                      <div className="mt-1 text-[11px] font-mono text-slate-400">
                        Accession: {f.accession_number}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {f.filing_url && (
                        <a
                          href={f.filing_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-[11px] text-blue-600 hover:text-blue-800 flex items-center gap-1 mr-2"
                        >
                          <span>SEC Archives</span>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                      {selected && <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0" />}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 text-xs text-slate-600">
              No previous filing cached for {selectedTicker}. The pipeline will fetch the latest verified 10-K directly from SEC EDGAR.
            </div>
          )}
        </div>

        {/* Step 3: Existing Audit Detection & Idempotency Controls */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
          <div className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
              3
            </span>
            <h2 className="text-base font-semibold text-slate-900">
              Audit Detection & Idempotency
            </h2>
          </div>

          {/* Existing Audit Alert Banner if detected */}
          {existingAuditMatch && (
            <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <FileCheck2 className="h-5 w-5 text-blue-600 shrink-0" />
                  <div>
                    <h3 className="text-xs font-bold text-blue-950">
                      Existing Audit Record Detected
                    </h3>
                    <p className="text-[11px] text-blue-800">
                      An audit for <span className="font-semibold">{selectedTicker}</span> already exists in local SQLite storage.
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => navigate(`/app/audits/${existingAuditMatch.run_id}`)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-blue-700 transition-colors shrink-0"
                >
                  <span>Open Existing Audit</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] bg-white/80 p-2.5 rounded-lg border border-blue-200/80 font-mono">
                <div>
                  <span className="text-slate-400 block">Run ID</span>
                  <span className="font-bold text-slate-800">{existingAuditMatch.run_id}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Status</span>
                  <span className="font-semibold text-blue-700">{existingAuditMatch.status}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Confidence</span>
                  <span className="font-bold text-emerald-700">
                    {existingAuditMatch.overall_confidence
                      ? `${(existingAuditMatch.overall_confidence * 100).toFixed(1)}%`
                      : '—'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">Created</span>
                  <span className="text-slate-600">
                    {existingAuditMatch.created_at
                      ? new Date(existingAuditMatch.created_at).toLocaleDateString()
                      : 'N/A'}
                  </span>
                </div>
              </div>
            </div>
          )}

          <div className="pt-1">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={forceReprocess}
                onChange={(e) => setForceReprocess(e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              <div>
                <span className="text-xs font-semibold text-slate-900">
                  Force Reprocess (Create Fresh Audit Run)
                </span>
                <p className="text-[11px] text-slate-500">
                  {existingAuditMatch
                    ? 'Check this box if you wish to bypass the existing audit record and re-execute the entire extraction and validation workflow from scratch.'
                    : 'If unchecked, FinovaLabs ensures zero duplicate executions by returning the deterministic audit checkpoint.'}
                </p>
              </div>
            </label>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3.5 flex items-start gap-2.5">
            <ShieldCheck className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
            <div className="text-xs text-slate-600 leading-relaxed">
              <span className="font-semibold text-slate-900">Tamper-Evident Idempotency:</span>{' '}
              FinovaLabs computes a cryptographic SHA-256 fingerprint from the CIK, Accession Number, and pipeline version. Repeated runs without force reprocess will safely restore the exact verified results.
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => navigate('/app')}
            className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-xs font-semibold text-white shadow-xs hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? (
              <>
                <RotateCcw className="h-4 w-4 animate-spin" />
                <span>Processing Audit...</span>
              </>
            ) : existingAuditMatch && !forceReprocess ? (
              <>
                <Play className="h-4 w-4" />
                <span>Resume / Retrieve Existing Audit</span>
              </>
            ) : (
              <>
                <Play className="h-4 w-4" />
                <span>Launch Financial Audit</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  )
}
