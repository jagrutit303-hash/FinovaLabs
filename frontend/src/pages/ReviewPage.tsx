import React, { useEffect, useState, useMemo } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import {
  CheckCircle2,
  XCircle,
  Edit3,
  Play,
  RotateCcw,
  ArrowRight,
  ShieldAlert,
  ShieldCheck,
  CheckCheck,
  Lock,
  ChevronRight,
} from 'lucide-react'
import { api } from '../api/client'
import type { ReviewTask, AuditRun } from '../api/client'

// Currency formatter for review cards
function formatReviewCurrency(val: any, unit = 'USD'): string {
  if (val === null || val === undefined || val === '' || val === '—') return '—'
  const str = String(val).trim().replace(/[$,\s]/g, '')
  const num = parseFloat(str)
  if (isNaN(num)) return String(val)
  const abs = Math.abs(num)
  const sign = num < 0 ? '-' : ''
  if (unit.toLowerCase().includes('share') || str.includes('.') && abs < 1000) {
    return `${sign}$${abs.toFixed(2)}/sh`
  }
  if (abs >= 1_000_000_000) {
    return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`
  }
  if (abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(2)}M`
  }
  if (abs >= 1_000) {
    return `${sign}$${(abs / 1_000).toFixed(1)}K`
  }
  return `${sign}$${abs.toLocaleString()}`
}

export const ReviewPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const runIdParam = searchParams.get('runId') || ''
  const [statusFilter, setStatusFilter] = useState<'OPEN' | 'RESOLVED' | 'ALL'>('OPEN')
  const [reviews, setReviews] = useState<ReviewTask[]>([])
  const [allReviews, setAllReviews] = useState<ReviewTask[]>([])
  const [audits, setAudits] = useState<AuditRun[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [workflowResumedAlert, setWorkflowResumedAlert] = useState<{
    runId: string
    status: string
  } | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Active action modal states
  const [selectedTask, setSelectedTask] = useState<ReviewTask | null>(null)
  const [actionType, setActionType] = useState<'APPROVE' | 'CORRECT' | 'REJECT' | 'BATCH_APPROVE' | null>(null)
  const [correctedValue, setCorrectedValue] = useState<string>('')
  const [notes, setNotes] = useState<string>('')
  const [submittingAction, setSubmittingAction] = useState<boolean>(false)
  const [resumingRunId, setResumingRunId] = useState<string | null>(null)

  // Fetch audits list for the dropdown filter
  useEffect(() => {
    api.getAudits()
      .then(setAudits)
      .catch(() => setAudits([]))
  }, [])

  const loadReviews = async () => {
    try {
      setLoading(true)
      // Load both filtered reviews and all reviews for badge counting
      const [filteredData, allData] = await Promise.all([
        api.getReviews(statusFilter === 'ALL' ? undefined : statusFilter, runIdParam || undefined),
        api.getReviews(undefined, runIdParam || undefined).catch(() => []),
      ])
      setReviews(filteredData)
      setAllReviews(allData)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to fetch review tasks.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadReviews()
  }, [statusFilter, runIdParam])

  // Count summaries
  const counts = useMemo(() => {
    const openCount = allReviews.filter((t) => t.status === 'OPEN' || t.status === 'PENDING').length
    const resolvedCount = allReviews.filter((t) => t.status === 'APPROVED' || t.status === 'CORRECTED' || t.status === 'REJECTED').length
    return { open: openCount, resolved: resolvedCount, total: allReviews.length }
  }, [allReviews])

  const handleResumeRun = async (runId: string) => {
    try {
      setResumingRunId(runId)
      const updated = await api.resumeAudit(runId)
      setActionMessage(`Workflow ${runId} resumed successfully (status: ${updated.status}).`)
      await loadReviews()
    } catch (err: any) {
      setErrorMessage(`Failed to resume: ${err.message}`)
    } finally {
      setResumingRunId(null)
    }
  }

  const openActionModal = (task: ReviewTask, type: 'APPROVE' | 'CORRECT' | 'REJECT') => {
    setSelectedTask(task)
    setActionType(type)
    setCorrectedValue(task.normalized_decimal || task.raw_value || '')
    setNotes(type === 'APPROVE' ? 'Approved by analyst as accurate Form 10-K extraction.' : '')
    setErrorMessage(null)
  }

  const openBatchApproveModal = () => {
    setActionType('BATCH_APPROVE')
    setSelectedTask(null)
    setNotes('Batch approved: analyst verified financial values against audited Form 10-K disclosures.')
    setErrorMessage(null)
  }

  const closeActionModal = () => {
    setSelectedTask(null)
    setActionType(null)
    setCorrectedValue('')
    setNotes('')
    setErrorMessage(null)
  }

  const handleDecisionSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!actionType) return

    setSubmittingAction(true)
    setErrorMessage(null)

    try {
      if (actionType === 'BATCH_APPROVE') {
        const pendingTasks = reviews.filter((t) => t.status === 'OPEN' || t.status === 'PENDING')
        const taskIds = pendingTasks.map((t) => t.task_id)
        if (taskIds.length === 0) {
          closeActionModal()
          return
        }

        const res = await api.batchApproveReviews(taskIds, { notes: notes.trim() })
        setActionMessage(`Batch approved ${res.approved_count} review task(s) successfully.`)
        if (res.resumed_workflow_status && res.resumed_run_id) {
          setWorkflowResumedAlert({
            runId: res.resumed_run_id,
            status: res.resumed_workflow_status,
          })
        }
      } else if (selectedTask) {
        if ((actionType === 'CORRECT' || actionType === 'REJECT') && !notes.trim()) {
          setErrorMessage('A non-empty audit justification note is mandatory for corrections and rejections.')
          setSubmittingAction(false)
          return
        }

        if (actionType === 'CORRECT' && !correctedValue.trim()) {
          setErrorMessage('Please provide a revised numeric value.')
          setSubmittingAction(false)
          return
        }

        if (actionType === 'APPROVE') {
          const res = await api.approveReview(selectedTask.task_id, {
            notes: notes.trim() || 'Approved by analyst.',
          })
          setActionMessage(`Review (${selectedTask.metric_name}) approved successfully.`)
          if (res.resumed_workflow_status && res.resumed_run_id) {
            setWorkflowResumedAlert({
              runId: res.resumed_run_id,
              status: res.resumed_workflow_status,
            })
          }
        } else if (actionType === 'CORRECT') {
          const res = await api.correctReview(selectedTask.task_id, {
            corrected_value: correctedValue.trim(),
            notes: notes.trim(),
          })
          setActionMessage(`Review (${selectedTask.metric_name}) corrected to ${correctedValue.trim()}.`)
          if (res.resumed_workflow_status && res.resumed_run_id) {
            setWorkflowResumedAlert({
              runId: res.resumed_run_id,
              status: res.resumed_workflow_status,
            })
          }
        } else if (actionType === 'REJECT') {
          const res = await api.rejectReview(selectedTask.task_id, {
            reason: notes.trim(),
            notes: notes.trim(),
          })
          setActionMessage(`Review (${selectedTask.metric_name}) rejected.`)
          if (res.resumed_workflow_status && res.resumed_run_id) {
            setWorkflowResumedAlert({
              runId: res.resumed_run_id,
              status: res.resumed_workflow_status,
            })
          }
        }
      }

      closeActionModal()
      await loadReviews()
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to record decision.')
    } finally {
      setSubmittingAction(false)
    }
  }

  const handleRunFilterChange = (rId: string) => {
    if (rId) {
      setSearchParams({ runId: rId })
    } else {
      setSearchParams({})
    }
  }

  return (
    <div className="py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto space-y-6 bg-[#FDFCFA]">
      {/* Header & Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
              Human-in-the-Loop Review Center
            </h1>
            <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-bold text-blue-700 ring-1 ring-blue-600/20">
              PS-01 HITL Gate
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Durable LangGraph checkpoint governance: inspect SEC 10-K citations, resolve exceptions, and commit immutable decisions.
          </p>
        </div>

        {/* Global Run Selector and Workflow Resume Actions */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <label htmlFor="runSelectFilter" className="text-xs font-semibold text-slate-700 whitespace-nowrap">
              Audit Run:
            </label>
            <select
              id="runSelectFilter"
              value={runIdParam}
              onChange={(e) => handleRunFilterChange(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-mono font-medium text-slate-800 shadow-2xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              <option value="">All Runs ({audits.length} Audits)</option>
              {audits.map((a) => (
                <option key={a.run_id} value={a.run_id}>
                  {a.ticker} ({a.run_id}) • {a.status}
                </option>
              ))}
            </select>
          </div>

          {runIdParam && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleResumeRun(runIdParam)}
                disabled={resumingRunId === runIdParam}
                className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white shadow-2xs hover:bg-amber-700 disabled:opacity-50 transition-colors cursor-pointer"
                title="Resume pipeline from persisted LangGraph checkpoint"
              >
                {resumingRunId === runIdParam ? (
                  <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                <span>Resume Pipeline</span>
              </button>

              <Link
                to={`/app/audits/${runIdParam}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
              >
                <span>Workspace</span>
                <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Workflow Resumed Alert Notification */}
      {workflowResumedAlert && (
        <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-6 w-6 text-emerald-600 shrink-0" />
            <div>
              <div className="text-xs font-bold text-emerald-950">
                All Human Review Tasks Resolved for {workflowResumedAlert.runId}!
              </div>
              <div className="text-xs text-emerald-800 mt-0.5">
                The LangGraph workflow resumed from its SQLite checkpoint and finalized with status:{' '}
                <span className="font-mono font-bold">{workflowResumedAlert.status}</span>.
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Link
              to={`/app/audits/${workflowResumedAlert.runId}`}
              className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-800"
            >
              <span>View Workspace</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              to={`/app/reports?runId=${workflowResumedAlert.runId}`}
              className="inline-flex items-center gap-1 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-50"
            >
              <span>View Accuracy Report</span>
            </Link>
            <button
              onClick={() => setWorkflowResumedAlert(null)}
              className="text-emerald-700 hover:text-emerald-900 text-xs font-bold px-2 py-1"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {actionMessage && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-xs font-medium text-emerald-900 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            <span>{actionMessage}</span>
          </div>
          <button onClick={() => setActionMessage(null)} className="font-bold text-emerald-700 hover:text-emerald-900 cursor-pointer">
            Dismiss
          </button>
        </div>
      )}

      {/* Filter Tabs & Batch Action Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setStatusFilter('OPEN')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              statusFilter === 'OPEN'
                ? 'bg-blue-600 text-white shadow-2xs font-bold'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`}
          >
            <span>Pending Review</span>
            <span
              className={`rounded-full px-2 py-0.2 text-[10px] font-mono ${
                statusFilter === 'OPEN' ? 'bg-blue-500 text-white' : 'bg-amber-100 text-amber-800'
              }`}
            >
              {counts.open}
            </span>
          </button>

          <button
            onClick={() => setStatusFilter('RESOLVED')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              statusFilter === 'RESOLVED'
                ? 'bg-blue-600 text-white shadow-2xs font-bold'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`}
          >
            <span>Resolved Decisions</span>
            <span
              className={`rounded-full px-2 py-0.2 text-[10px] font-mono ${
                statusFilter === 'RESOLVED' ? 'bg-blue-500 text-white' : 'bg-slate-200 text-slate-700'
              }`}
            >
              {counts.resolved}
            </span>
          </button>

          <button
            onClick={() => setStatusFilter('ALL')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              statusFilter === 'ALL'
                ? 'bg-blue-600 text-white shadow-2xs font-bold'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
            }`}
          >
            <span>All Tasks</span>
            <span
              className={`rounded-full px-2 py-0.2 text-[10px] font-mono ${
                statusFilter === 'ALL' ? 'bg-blue-500 text-white' : 'bg-slate-200 text-slate-700'
              }`}
            >
              {counts.total}
            </span>
          </button>
        </div>

        {/* Batch Approval Action for Pending items */}
        {statusFilter !== 'RESOLVED' && counts.open > 0 && (
          <button
            onClick={openBatchApproveModal}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-2xs hover:bg-emerald-700 transition-colors cursor-pointer"
          >
            <CheckCheck className="h-4 w-4" />
            <span>Approve All Visible Pending ({reviews.filter((t) => t.status === 'OPEN' || t.status === 'PENDING').length})</span>
          </button>
        )}
      </div>

      {/* Task List */}
      {loading ? (
        <div className="py-20 text-center text-xs text-slate-400">
          <RotateCcw className="h-6 w-6 text-blue-600 animate-spin mx-auto mb-2" />
          Loading review tasks from SQLite database...
        </div>
      ) : reviews.length === 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center shadow-xs space-y-3">
          <CheckCircle2 className="h-12 w-12 text-emerald-500 mx-auto" />
          <h3 className="text-base font-bold text-slate-900">
            {statusFilter === 'OPEN' ? 'No Pending Reviews Found' : 'No Review Records Available'}
          </h3>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            {statusFilter === 'OPEN'
              ? 'All metrics for the selected scope meet or exceed the required confidence cutoff and passed deterministic validation checks.'
              : 'No historical human review decisions match the current filter selection.'}
          </p>
          {statusFilter === 'OPEN' && counts.resolved > 0 && (
            <button
              onClick={() => setStatusFilter('RESOLVED')}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800 underline pt-1 cursor-pointer"
            >
              <span>View {counts.resolved} Resolved Historical Decisions</span>
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {reviews.map((task) => {
            const isPending = task.status === 'OPEN' || task.status === 'PENDING'
            const isApproved = task.status === 'APPROVED'
            const isCorrected = task.status === 'CORRECTED'

            const rawDec = task.normalized_decimal || task.raw_value
            const formattedExtracted = formatReviewCurrency(rawDec, task.unit || 'USD')
            const formattedResolved = task.resolved_decimal ? formatReviewCurrency(task.resolved_decimal, task.unit || 'USD') : null

            const confScore = task.confidence_score !== undefined && task.confidence_score !== null ? task.confidence_score : null
            const confThreshold = task.confidence_threshold !== undefined && task.confidence_threshold !== null ? task.confidence_threshold : 0.80

            return (
              <div
                key={task.task_id}
                className={`rounded-2xl border bg-white p-5 shadow-xs transition-all space-y-4 ${
                  isPending
                    ? 'border-amber-200 ring-1 ring-amber-400/20 hover:border-amber-300'
                    : isApproved
                    ? 'border-emerald-200/80 hover:border-emerald-300'
                    : isCorrected
                    ? 'border-purple-200/80 hover:border-purple-300'
                    : 'border-rose-200/80 hover:border-rose-300'
                }`}
              >
                {/* Header: Metric, Ticker, Status & Action Buttons */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-bold text-slate-900">{task.metric_name}</span>
                      {task.ticker && (
                        <span className="rounded-md bg-slate-900 px-2 py-0.5 text-xs font-mono font-bold text-white">
                          {task.ticker}
                        </span>
                      )}
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                          isPending
                            ? 'bg-amber-100 text-amber-800 ring-1 ring-amber-400/30'
                            : isApproved
                            ? 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-500/30'
                            : isCorrected
                            ? 'bg-purple-100 text-purple-800 ring-1 ring-purple-500/30'
                            : 'bg-rose-100 text-rose-800 ring-1 ring-rose-500/30'
                        }`}
                      >
                        {isPending ? 'PENDING ACTION' : task.status}
                      </span>
                    </div>

                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] font-mono text-slate-400">
                      <span>Task: {task.task_id}</span>
                      <span>•</span>
                      {task.run_id && (
                        <Link to={`/app/audits/${task.run_id}`} className="hover:text-blue-600 underline">
                          Run: {task.run_id}
                        </Link>
                      )}
                      <span>•</span>
                      <span>Accession: {task.accession_number || '10-K'}</span>
                    </div>
                  </div>

                  {/* Actions for Pending Tasks */}
                  {isPending && (
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => openActionModal(task, 'APPROVE')}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-2xs hover:bg-emerald-700 transition-colors cursor-pointer"
                        title="Approve extracted value as verified ground truth"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        <span>Approve</span>
                      </button>

                      <button
                        onClick={() => openActionModal(task, 'CORRECT')}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-2xs hover:bg-blue-700 transition-colors cursor-pointer"
                        title="Correct value with revised Decimal and mandatory justification"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                        <span>Correct Value</span>
                      </button>

                      <button
                        onClick={() => openActionModal(task, 'REJECT')}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer"
                        title="Reject extracted metric with required reason"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        <span>Reject</span>
                      </button>
                    </div>
                  )}
                </div>

                {/* Values Comparison & Confidence Meter */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                  {/* Extracted Value */}
                  <div className="rounded-xl bg-slate-50 p-3.5 border border-slate-200/80 space-y-1">
                    <span className="text-[11px] font-medium text-slate-500 block">
                      Extracted Value (Raw & Normalized)
                    </span>
                    <div className="flex items-baseline gap-2">
                      <span className="font-mono text-lg font-bold text-slate-900">
                        {formattedExtracted}
                      </span>
                      <span className="text-[11px] font-mono text-slate-500">
                        ({task.unit || 'USD'})
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-slate-400 block truncate" title={rawDec || ''}>
                      Decimal: {rawDec || '—'}
                    </span>
                  </div>

                  {/* Resolved / Approved Value */}
                  <div className={`rounded-xl p-3.5 border space-y-1 ${
                    isPending
                      ? 'bg-slate-50 border-slate-200/80'
                      : isApproved
                      ? 'bg-emerald-50/50 border-emerald-200'
                      : isCorrected
                      ? 'bg-purple-50/50 border-purple-200'
                      : 'bg-rose-50/50 border-rose-200'
                  }`}>
                    <span className="text-[11px] font-medium text-slate-500 block">
                      Analyst Governed Figure
                    </span>
                    <div className="flex items-baseline gap-2">
                      <span className="font-mono text-lg font-bold text-slate-900">
                        {formattedResolved || (isPending ? 'Pending Analyst Action' : formattedExtracted)}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-slate-500 block">
                      {isPending ? 'Workflow paused on checkpoint' : `Status: ${task.status}`}
                    </span>
                  </div>

                  {/* Confidence Score & Cutoff */}
                  <div className="rounded-xl bg-slate-50 p-3.5 border border-slate-200/80 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="font-medium text-slate-500">Extraction Confidence:</span>
                      <span className="font-mono font-bold text-slate-800">
                        {confScore !== null ? `${(confScore * 100).toFixed(1)}%` : 'N/A'}
                      </span>
                    </div>
                    <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all duration-500 ${
                          confScore !== null && confScore >= confThreshold
                            ? 'bg-emerald-500'
                            : 'bg-amber-500'
                        }`}
                        style={{ width: `${confScore !== null ? Math.min(confScore * 100, 100) : 0}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-400 block">
                      Auto-approve threshold: {(confThreshold * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                {/* Escalation Trigger Explanation Banner */}
                <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3 text-xs flex items-start gap-2.5">
                  <ShieldAlert className="h-4 w-4 text-amber-700 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold text-amber-950 block">Escalation Trigger:</span>
                    <p className="text-amber-900 text-xs mt-0.5 font-sans leading-relaxed">
                      {task.reason || 'Confidence cutoff breach requiring human analyst verification.'}
                    </p>
                  </div>
                </div>

                {/* Verbatim Source Evidence Citation */}
                {task.source_evidence && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3 text-xs space-y-1">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="font-bold text-slate-700">
                        Verbatim SEC Filing Citation ({task.evidence_location || '10-K Section'}):
                      </span>
                      <span className="font-mono text-slate-400">Exact Excerpt</span>
                    </div>
                    <p className="font-mono text-[11px] text-slate-700 bg-white p-2.5 rounded-lg border border-slate-200 italic leading-relaxed">
                      "{task.source_evidence}"
                    </p>
                  </div>
                )}

                {/* Resolved Decision Metadata & Audit Trail */}
                {!isPending && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div>
                      <span className="font-semibold text-slate-900">Analyst Audit Note: </span>
                      <span className="text-slate-700 font-sans">{task.reviewer_note || 'Approved as extracted.'}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 font-mono shrink-0">
                      Sign-off: <span className="font-bold text-slate-800">{task.resolved_by || 'analyst'}</span> •{' '}
                      {task.resolved_at ? new Date(task.resolved_at).toLocaleString() : 'Recorded'}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ACTION MODAL (Approve, Correct, Reject, Batch Approve) */}
      {actionType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl space-y-5">
            <div className="border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                {actionType === 'APPROVE' && <CheckCircle2 className="h-5 w-5 text-emerald-600" />}
                {actionType === 'CORRECT' && <Edit3 className="h-5 w-5 text-blue-600" />}
                {actionType === 'REJECT' && <XCircle className="h-5 w-5 text-rose-600" />}
                {actionType === 'BATCH_APPROVE' && <CheckCheck className="h-5 w-5 text-emerald-600" />}

                {actionType === 'APPROVE' && 'Approve Extracted Metric Value'}
                {actionType === 'CORRECT' && 'Correct Extracted Metric Value'}
                {actionType === 'REJECT' && 'Reject Extracted Metric Value'}
                {actionType === 'BATCH_APPROVE' && 'Batch Approve Visible Tasks'}
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                {actionType === 'BATCH_APPROVE' ? (
                  <span>
                    Confirm approval for all {reviews.filter((t) => t.status === 'OPEN' || t.status === 'PENDING').length} pending review items.
                  </span>
                ) : (
                  <span>
                    Target: <span className="font-bold text-slate-800">{selectedTask?.metric_name}</span> ({selectedTask?.ticker} • {selectedTask?.task_id})
                  </span>
                )}
              </p>
            </div>

            {errorMessage && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">
                {errorMessage}
              </div>
            )}

            <form onSubmit={handleDecisionSubmit} className="space-y-4">
              {/* Highlight original value for single task */}
              {selectedTask && (
                <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-xs">
                  <div className="text-slate-500 text-[11px]">Original Extracted Amount:</div>
                  <div className="text-sm font-bold font-mono text-slate-900 mt-0.5">
                    {formatReviewCurrency(selectedTask.normalized_decimal || selectedTask.raw_value, selectedTask.unit || 'USD')}
                    <span className="text-xs font-normal text-slate-500 ml-2">
                      ({selectedTask.normalized_decimal || selectedTask.raw_value})
                    </span>
                  </div>
                </div>
              )}

              {actionType === 'CORRECT' && (
                <div>
                  <label className="block text-xs font-semibold text-slate-800 mb-1">
                    Revised Normalized Value (Exact Python Decimal) <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={correctedValue}
                    onChange={(e) => setCorrectedValue(e.target.value)}
                    placeholder="e.g. 391035000000"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono font-bold text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    required
                  />
                  {correctedValue && (
                    <span className="text-[11px] text-blue-700 font-mono block mt-1">
                      Formatted Preview: {formatReviewCurrency(correctedValue, selectedTask?.unit || 'USD')}
                    </span>
                  )}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-800 mb-1">
                  Audit Justification Note {actionType !== 'APPROVE' && actionType !== 'BATCH_APPROVE' && <span className="text-rose-500">*</span>}
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={
                    actionType === 'APPROVE' || actionType === 'BATCH_APPROVE'
                      ? 'Analyst audit notes for record-keeping...'
                      : 'Provide verifiable explanation and SEC 10-K citation for this correction or rejection...'
                  }
                  rows={3}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  required={actionType === 'CORRECT' || actionType === 'REJECT'}
                />
              </div>

              <div className="flex items-center justify-between text-[11px] text-slate-500 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                <span className="flex items-center gap-1">
                  <Lock className="h-3 w-3 text-slate-400" />
                  Tamper-evident SHA-256 hash appended to audit ledger.
                </span>
                <span className="font-semibold text-emerald-700">Auto-resumes on final task</span>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={closeActionModal}
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submittingAction}
                  className={`rounded-lg px-5 py-2 text-xs font-semibold text-white transition-colors cursor-pointer ${
                    actionType === 'APPROVE' || actionType === 'BATCH_APPROVE'
                      ? 'bg-emerald-600 hover:bg-emerald-700'
                      : actionType === 'CORRECT'
                      ? 'bg-blue-600 hover:bg-blue-700'
                      : 'bg-rose-600 hover:bg-rose-700'
                  }`}
                >
                  {submittingAction
                    ? 'Recording Decision...'
                    : actionType === 'BATCH_APPROVE'
                    ? 'Confirm Batch Approval'
                    : `Confirm ${actionType}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
