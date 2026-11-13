import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  PlusCircle,
  Play,
  ArrowRight,
  AlertTriangle,
  CheckCircle2,
  FileCheck2,
  RotateCcw,
} from 'lucide-react'
import { api } from '../api/client'
import type { AuditRun, DashboardSummary } from '../api/client'

export const OverviewPage: React.FC = () => {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [recentAudits, setRecentAudits] = useState<AuditRun[]>([])
  const [loading, setLoading] = useState(true)
  const [resumingRunId, setResumingRunId] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  const loadData = async () => {
    try {
      setLoading(true)
      const [sumData, auditsData] = await Promise.all([
        api.getSummary().catch(() => ({
          total_runs: 0,
          total_filings: 0,
          open_reviews: 0,
          resolved_reviews: 0,
          failed_validations: 0,
          audit_events: 0,
        })),
        api.getAudits().catch(() => []),
      ])
      setSummary(sumData)
      setRecentAudits(auditsData)
    } catch {
      // safe fallback
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleResume = async (runId: string) => {
    try {
      setResumingRunId(runId)
      setActionMessage(null)
      const updated = await api.resumeAudit(runId)
      setActionMessage(`Workflow ${runId} resumed successfully (status: ${updated.status}).`)
      await loadData()
    } catch (err: any) {
      setActionMessage(`Resumption error: ${err.message}`)
    } finally {
      setResumingRunId(null)
    }
  }

  const pausedAudits = recentAudits.filter(
    (a) => a.status === 'PAUSED_FOR_REVIEW' || a.status === 'WAITING_FOR_REVIEW'
  )

  return (
    <div className="py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto space-y-8">
      {/* Action Notification Banner */}
      {actionMessage && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-xs font-medium text-blue-900 flex items-center justify-between">
          <span>{actionMessage}</span>
          <button
            onClick={() => setActionMessage(null)}
            className="text-blue-600 hover:text-blue-800 font-bold"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Top Section: Concise Welcome & Primary Action */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-6">
        <div>
          <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
            Operational Audit Workspace
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Execute SEC 10-K metric extractions, resolve flagged items, and inspect tamper-evident audit trails.
          </p>
        </div>
        <div>
          <Link
            to="/app/audits/new"
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 transition-colors focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            <PlusCircle className="h-4 w-4" />
            <span>Start a New Audit</span>
          </Link>
        </div>
      </div>

      {/* Operational Counts Bar (Computed from real DB records) */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <span className="text-xs font-medium text-slate-500">Total Audits</span>
          <div className="mt-1 text-2xl font-bold text-slate-900">
            {summary ? summary.total_runs : '—'}
          </div>
          <span className="text-[11px] text-slate-400">All pipeline executions</span>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <span className="text-xs font-medium text-slate-500">10-K Filings</span>
          <div className="mt-1 text-2xl font-bold text-slate-900">
            {summary ? summary.total_filings : '—'}
          </div>
          <span className="text-[11px] text-slate-400">Cached from SEC EDGAR</span>
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 shadow-xs">
          <span className="text-xs font-semibold text-amber-800">Pending Reviews</span>
          <div className="mt-1 text-2xl font-bold text-amber-900">
            {summary ? summary.open_reviews : '—'}
          </div>
          <span className="text-[11px] text-amber-700">Awaiting human signoff</span>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <span className="text-xs font-medium text-slate-500">Resolved Reviews</span>
          <div className="mt-1 text-2xl font-bold text-emerald-600">
            {summary ? summary.resolved_reviews : '—'}
          </div>
          <span className="text-[11px] text-slate-400">Analyst verified</span>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <span className="text-xs font-medium text-slate-500">Validation Flags</span>
          <div className="mt-1 text-2xl font-bold text-slate-800">
            {summary ? summary.failed_validations : '—'}
          </div>
          <span className="text-[11px] text-slate-400">Variance / Identity alerts</span>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <span className="text-xs font-medium text-slate-500">Audit Events</span>
          <div className="mt-1 text-2xl font-bold text-indigo-600">
            {summary ? summary.audit_events : '—'}
          </div>
          <span className="text-[11px] text-slate-400">SHA-256 chain records</span>
        </div>
      </div>

      {/* Paused & Interrupted Workflows Section (if any) */}
      {pausedAudits.length > 0 && (
        <div className="rounded-xl border border-amber-300 bg-amber-50/40 p-5 shadow-xs">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            <h2 className="text-sm font-semibold text-amber-900">
              Interrupted Workflows Requiring Attention ({pausedAudits.length})
            </h2>
          </div>
          <p className="text-xs text-amber-800 mb-4">
            The LangGraph checkpoint state machine paused these audit runs because confidence thresholds were breached or validations flagged discrepancies. Resolve items in the Review Center or resume when ready.
          </p>

          <div className="space-y-2.5">
            {pausedAudits.map((audit) => (
              <div
                key={audit.run_id}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-amber-200 bg-white p-3.5 shadow-xs"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-slate-900">
                      {audit.run_id}
                    </span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-800">
                      {audit.ticker}
                    </span>
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                      {audit.status}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    Step: <span className="font-mono">{audit.current_step || 'human_review'}</span> • Accession:{' '}
                    <span className="font-mono">{audit.accession_number || 'Latest 10-K'}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Link
                    to={`/app/reviews?runId=${audit.run_id}`}
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <span>Resolve Reviews</span>
                  </Link>
                  <button
                    onClick={() => handleResume(audit.run_id)}
                    disabled={resumingRunId === audit.run_id}
                    className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                  >
                    {resumingRunId === audit.run_id ? (
                      <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    <span>Resume Workflow</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Audit Activity Table */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 bg-slate-50/50">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Recent Audit Filings</h2>
            <p className="text-xs text-slate-500">
              Historical and active financial audits recorded in local SQLite database.
            </p>
          </div>
          <Link
            to="/app/audits/new"
            className="text-xs font-medium text-blue-600 hover:text-blue-800 inline-flex items-center gap-1"
          >
            <span>Run New Audit</span>
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>

        {loading ? (
          <div className="py-12 text-center text-xs text-slate-400">Loading audit records...</div>
        ) : recentAudits.length === 0 ? (
          /* Useful Empty State */
          <div className="py-14 text-center px-4">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600 mb-3">
              <FileCheck2 className="h-6 w-6" />
            </div>
            <h3 className="text-sm font-semibold text-slate-900">No Audits Found</h3>
            <p className="mt-1 text-xs text-slate-500 max-w-sm mx-auto">
              Start your first financial filing audit to retrieve SEC 10-K data, extract key financial metrics with Decimal precision, and run accounting validation.
            </p>
            <div className="mt-5">
              <Link
                to="/app/audits/new"
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-blue-700"
              >
                <PlusCircle className="h-4 w-4" />
                <span>Start your first audit</span>
              </Link>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <th className="py-3 px-4 sm:px-6">Run ID</th>
                  <th className="py-3 px-4">Company</th>
                  <th className="py-3 px-4">Filing Accession</th>
                  <th className="py-3 px-4">Fiscal Year</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4">Last Updated</th>
                  <th className="py-3 px-4 text-right sm:px-6">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {recentAudits.map((audit) => {
                  const confPct = audit.overall_confidence
                    ? (audit.overall_confidence * 100).toFixed(1) + '%'
                    : '—'
                  const isPaused =
                    audit.status === 'PAUSED_FOR_REVIEW' || audit.status === 'WAITING_FOR_REVIEW'
                  const isCompleted = audit.status === 'COMPLETED'

                  return (
                    <tr
                      key={audit.run_id}
                      className="hover:bg-slate-50/80 transition-colors cursor-pointer"
                      onClick={() => navigate(`/app/audits/${audit.run_id}`)}
                    >
                      <td className="py-3.5 px-4 sm:px-6 font-mono font-medium text-blue-700">
                        {audit.run_id}
                      </td>
                      <td className="py-3.5 px-4 font-semibold text-slate-900">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-bold text-slate-800">
                            {audit.ticker}
                          </span>
                        </span>
                      </td>
                      <td className="py-3.5 px-4 font-mono text-[11px] text-slate-500">
                        {audit.accession_number || 'Pending'}
                      </td>
                      <td className="py-3.5 px-4 text-slate-700">
                        {audit.fiscal_year ? `FY${audit.fiscal_year}` : '—'}
                      </td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            isCompleted
                              ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20'
                              : isPaused
                              ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-600/20'
                              : 'bg-blue-50 text-blue-700 ring-1 ring-blue-600/20'
                          }`}
                        >
                          {isCompleted && <CheckCircle2 className="h-3 w-3" />}
                          {isPaused && <AlertTriangle className="h-3 w-3" />}
                          <span>{audit.status}</span>
                        </span>
                      </td>
                      <td className="py-3.5 px-4 font-semibold text-slate-800">
                        {confPct}
                      </td>
                      <td className="py-3.5 px-4 text-slate-500 text-[11px]">
                        {audit.updated_at ? new Date(audit.updated_at).toLocaleString() : '—'}
                      </td>
                      <td className="py-3.5 px-4 text-right sm:px-6" onClick={(e) => e.stopPropagation()}>
                        <Link
                          to={`/app/audits/${audit.run_id}`}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800"
                        >
                          <span>Workspace</span>
                          <ArrowRight className="h-3 w-3" />
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
