import React, { useEffect, useState, useRef, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  RotateCcw,
  Play,
  FileText,
  X,
  FileCheck2,
  Download,
  TrendingUp,
  CheckCheck,
  Edit3,
  XCircle,
  ShieldAlert,
  Lock,
} from 'lucide-react'
import { api } from '../api/client'
import type {
  AuditRun,
  ExtractedMetric,
  ValidationResult,
  EvidenceCitation,
  AuditReport,
  AuditEvent,
  ReviewTask,
} from '../api/client'

// Format financial currency
function formatWorkspaceCurrency(val: any, unit = 'USD'): string {
  if (val === null || val === undefined || val === '' || val === '—') return '—'
  const str = String(val).trim().replace(/[$,\s]/g, '')
  const num = parseFloat(str)
  if (isNaN(num)) return String(val)
  const abs = Math.abs(num)
  const sign = num < 0 ? '-' : ''
  if (unit.toLowerCase().includes('share') || (str.includes('.') && abs < 1000)) {
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

export const AuditWorkspacePage: React.FC = () => {
  const { auditId } = useParams<{ auditId: string }>()

  const [audit, setAudit] = useState<AuditRun | null>(null)
  const [metrics, setMetrics] = useState<ExtractedMetric[]>([])
  const [validations, setValidations] = useState<ValidationResult[]>([])
  const [evidenceList, setEvidenceList] = useState<EvidenceCitation[]>([])
  const [report, setReport] = useState<AuditReport | null>(null)
  const [history, setHistory] = useState<AuditEvent[]>([])
  const [reviewTasks, setReviewTasks] = useState<ReviewTask[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Collapsible methodology state
  const [showMethodology, setShowMethodology] = useState<boolean>(false)

  // Evidence Modal state
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceCitation | null>(null)

  // Workflow resumption & action state
  const [resuming, setResuming] = useState<boolean>(false)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)

  // Inline Review Action Modal states
  const [selectedReviewTask, setSelectedReviewTask] = useState<ReviewTask | null>(null)
  const [reviewActionType, setReviewActionType] = useState<'APPROVE' | 'CORRECT' | 'REJECT' | 'BATCH_APPROVE' | null>(null)
  const [reviewCorrectedVal, setReviewCorrectedVal] = useState<string>('')
  const [reviewNotes, setReviewNotes] = useState<string>('')
  const [submittingReviewAction, setSubmittingReviewAction] = useState<boolean>(false)

  // Polling ref
  const pollTimerRef = useRef<any>(null)

  const loadAuditData = async (isBackgroundPoll = false) => {
    if (!auditId) return
    try {
      if (!isBackgroundPoll) setLoading(true)
      setError(null)
      const [runData, metricsData, validationsData, evidenceData, reportData, historyData, reviewsData] = await Promise.all([
        api.getAudit(auditId),
        api.getAuditResults(auditId).catch(() => []),
        api.getAuditValidations(auditId).catch(() => []),
        api.getAuditEvidence(auditId).catch(() => []),
        api.getAuditReport(auditId).catch(() => null),
        api.getAuditHistory(auditId).catch(() => []),
        api.getReviews(undefined, auditId).catch(() => []),
      ])
      setAudit(runData)
      setMetrics(metricsData)
      setValidations(validationsData)
      setEvidenceList(evidenceData)
      setReport(reportData)
      setHistory(historyData)
      setReviewTasks(reviewsData)
    } catch (err: any) {
      if (!isBackgroundPoll) {
        setError(err.message || 'Failed to load audit workspace.')
      }
    } finally {
      if (!isBackgroundPoll) setLoading(false)
    }
  }

  useEffect(() => {
    loadAuditData()

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [auditId])

  // Active polling if audit is currently in progress
  useEffect(() => {
    if (audit && (audit.status === 'RUNNING' || audit.status === 'PROCESSING' || audit.status === 'IN_PROGRESS')) {
      pollTimerRef.current = setInterval(() => {
        loadAuditData(true)
      }, 2000)
    } else {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [audit?.status])

  // Pending review tasks for this audit run
  const openReviewTasks = useMemo(() => {
    return reviewTasks.filter((t) => t.status === 'OPEN' || t.status === 'PENDING')
  }, [reviewTasks])

  const handleResume = async () => {
    if (!auditId) return
    try {
      setResuming(true)
      setActionSuccess(null)
      const updated = await api.resumeAudit(auditId)
      setActionSuccess(`Workflow resumed successfully: status is now ${updated.status}.`)
      await loadAuditData()
    } catch (err: any) {
      setError(`Failed to resume workflow: ${err.message}`)
    } finally {
      setResuming(false)
    }
  }

  const openReviewModal = (task: ReviewTask, type: 'APPROVE' | 'CORRECT' | 'REJECT') => {
    setSelectedReviewTask(task)
    setReviewActionType(type)
    setReviewCorrectedVal(task.normalized_decimal || task.raw_value || '')
    setReviewNotes(type === 'APPROVE' ? 'Approved as verified by analyst.' : '')
    setError(null)
  }

  const openBatchApproveModal = () => {
    setReviewActionType('BATCH_APPROVE')
    setSelectedReviewTask(null)
    setReviewNotes('Batch approved: analyst verified financial values against Form 10-K.')
    setError(null)
  }

  const closeReviewModal = () => {
    setSelectedReviewTask(null)
    setReviewActionType(null)
    setReviewCorrectedVal('')
    setReviewNotes('')
  }

  const handleReviewDecisionSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!reviewActionType) return

    setSubmittingReviewAction(true)
    setError(null)

    try {
      if (reviewActionType === 'BATCH_APPROVE') {
        const taskIds = openReviewTasks.map((t) => t.task_id)
        if (taskIds.length === 0) {
          closeReviewModal()
          return
        }

        const res = await api.batchApproveReviews(taskIds, { notes: reviewNotes.trim() })
        setActionSuccess(`Batch approved ${res.approved_count} review task(s). Workflow finalized with status: ${res.resumed_workflow_status || 'COMPLETED'}.`)
      } else if (selectedReviewTask) {
        if ((reviewActionType === 'CORRECT' || reviewActionType === 'REJECT') && !reviewNotes.trim()) {
          setError('A non-empty audit justification note is mandatory for corrections and rejections.')
          setSubmittingReviewAction(false)
          return
        }

        if (reviewActionType === 'CORRECT' && !reviewCorrectedVal.trim()) {
          setError('Please provide a revised numeric value.')
          setSubmittingReviewAction(false)
          return
        }

        if (reviewActionType === 'APPROVE') {
          const res = await api.approveReview(selectedReviewTask.task_id, {
            notes: reviewNotes.trim() || 'Approved by analyst.',
          })
          if (res.remaining_open_tasks === 0) {
            setActionSuccess(`All review items resolved! Workflow resumed from checkpoint and finalized with status: ${res.resumed_workflow_status || 'COMPLETED'}.`)
          } else {
            setActionSuccess(`Review (${selectedReviewTask.metric_name}) approved. ${res.remaining_open_tasks} remaining.`)
          }
        } else if (reviewActionType === 'CORRECT') {
          const res = await api.correctReview(selectedReviewTask.task_id, {
            corrected_value: reviewCorrectedVal.trim(),
            notes: reviewNotes.trim(),
          })
          if (res.remaining_open_tasks === 0) {
            setActionSuccess(`All review items resolved! Workflow resumed from checkpoint and finalized with status: ${res.resumed_workflow_status || 'COMPLETED'}.`)
          } else {
            setActionSuccess(`Review (${selectedReviewTask.metric_name}) corrected to ${reviewCorrectedVal.trim()}. ${res.remaining_open_tasks} remaining.`)
          }
        } else if (reviewActionType === 'REJECT') {
          const res = await api.rejectReview(selectedReviewTask.task_id, {
            reason: reviewNotes.trim(),
            notes: reviewNotes.trim(),
          })
          if (res.remaining_open_tasks === 0) {
            setActionSuccess(`All review items resolved! Workflow resumed and finalized with status: ${res.resumed_workflow_status || 'COMPLETED'}.`)
          } else {
            setActionSuccess(`Review (${selectedReviewTask.metric_name}) rejected. ${res.remaining_open_tasks} remaining.`)
          }
        }
      }

      closeReviewModal()
      await loadAuditData()
    } catch (err: any) {
      setError(err.message || 'Failed to record review decision.')
    } finally {
      setSubmittingReviewAction(false)
    }
  }

  const exportReportJson = () => {
    if (!audit) return
    const exportData = {
      audit,
      metrics,
      validations,
      report,
      evidence_citations_count: evidenceList.length,
      history_events_count: history.length,
      exported_at: new Date().toISOString(),
    }
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `finova_audit_${audit.run_id}_${audit.ticker}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportAuditCsv = () => {
    if (history.length === 0) return
    const headers = ['event_id', 'seq_id', 'run_id', 'event_type', 'actor', 'original_value', 'corrected_value', 'prev_hash', 'event_hash', 'created_at']
    const rows = history.map((e) => [
      e.event_id,
      e.seq_id || '',
      `"${e.run_id || ''}"`,
      `"${e.event_type}"`,
      `"${e.actor}"`,
      `"${e.original_value || ''}"`,
      `"${e.corrected_value || ''}"`,
      `"${e.prev_hash}"`,
      `"${e.event_hash}"`,
      `"${e.created_at}"`,
    ])
    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `finova_audit_trail_${audit?.run_id}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return (
      <div className="py-24 text-center">
        <RotateCcw className="h-8 w-8 text-blue-600 animate-spin mx-auto mb-3" />
        <p className="text-sm font-medium text-slate-700">Loading audit workspace for {auditId}...</p>
        <p className="text-xs text-slate-400 mt-1">Retrieving verified metrics from SQLite storage</p>
      </div>
    )
  }

  if (error && !audit) {
    return (
      <div className="py-12 max-w-3xl mx-auto px-4">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-center space-y-4">
          <AlertTriangle className="h-8 w-8 text-rose-600 mx-auto" />
          <h2 className="text-lg font-semibold text-rose-900">Audit Not Found</h2>
          <p className="text-xs text-rose-700">{error || 'Unable to locate the specified audit run.'}</p>
          <Link
            to="/app"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white"
          >
            Return to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  if (!audit) return null

  const confidenceValue = audit.overall_confidence ?? 0.0
  const confidencePercent = (confidenceValue * 100).toFixed(1)
  const isHighConfidence = confidenceValue >= 0.90
  const isMediumConfidence = confidenceValue >= 0.60 && confidenceValue < 0.90
  const isPaused = audit.status === 'PAUSED_FOR_REVIEW' || audit.status === 'WAITING_FOR_REVIEW' || openReviewTasks.length > 0
  const isCompleted = audit.status === 'COMPLETED' || audit.status === 'COMPLETED_WITH_REJECTIONS'
  const isRunning = audit.status === 'RUNNING' || audit.status === 'PROCESSING' || audit.status === 'IN_PROGRESS'

  return (
    <div className="py-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto space-y-8 bg-[#FDFCFA]">
      {/* Top Banner / Breadcrumb & Status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
            <Link to="/app" className="hover:text-blue-600">Workspaces</Link>
            <span>/</span>
            <span className="font-mono text-slate-700 font-semibold">{audit.run_id}</span>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
              {audit.ticker} 10-K Audit Workspace
            </h1>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                isCompleted
                  ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20'
                  : isPaused
                  ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-600/20'
                  : 'bg-blue-50 text-blue-700 ring-1 ring-blue-600/20'
              }`}
            >
              {isCompleted && <CheckCircle2 className="h-3.5 w-3.5" />}
              {isPaused && <AlertTriangle className="h-3.5 w-3.5" />}
              {isRunning && <RotateCcw className="h-3.5 w-3.5 animate-spin" />}
              <span>{audit.status}</span>
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-500 font-mono">
            Accession: {audit.accession_number || 'N/A'} • Fiscal Year: {audit.fiscal_year ? `FY${audit.fiscal_year}` : 'Latest'}
          </div>
        </div>

        {/* Action Buttons: Resume, Review, Exports */}
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to={`/app/analytics?auditId=${audit.run_id}`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-semibold text-white shadow-2xs hover:bg-blue-700 transition-colors"
          >
            <TrendingUp className="h-3.5 w-3.5" />
            <span>Interactive Analytics</span>
          </Link>

          {isPaused && (
            <>
              <Link
                to={`/app/reviews?runId=${audit.run_id}`}
                className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 text-xs font-semibold text-white shadow-2xs hover:bg-amber-700 transition-colors"
              >
                <AlertTriangle className="h-3.5 w-3.5" />
                <span>Review Center ({openReviewTasks.length})</span>
              </Link>
              <button
                onClick={handleResume}
                disabled={resuming}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors cursor-pointer"
              >
                {resuming ? <RotateCcw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                <span>Resume Pipeline</span>
              </button>
            </>
          )}

          {/* Direct JSON and CSV Exports */}
          <button
            onClick={exportReportJson}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors cursor-pointer"
            title="Download full audit report as JSON"
          >
            <Download className="h-3.5 w-3.5 text-slate-500" />
            <span>JSON</span>
          </button>
          <button
            onClick={exportAuditCsv}
            disabled={history.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors cursor-pointer"
            title="Download cryptographic audit trail as CSV"
          >
            <Download className="h-3.5 w-3.5 text-slate-500" />
            <span>CSV Ledger</span>
          </button>
          <Link
            to={`/app/reports?runId=${audit.run_id}`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 transition-colors"
          >
            <FileText className="h-3.5 w-3.5 text-slate-300" />
            <span>Full Report</span>
          </Link>
        </div>
      </div>

      {actionSuccess && (
        <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-xs font-medium text-emerald-900 flex items-center justify-between shadow-2xs">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            <span>{actionSuccess}</span>
          </div>
          <button onClick={() => setActionSuccess(null)} className="font-bold text-emerald-700 hover:text-emerald-900 cursor-pointer">
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs font-medium text-rose-900 flex items-center justify-between shadow-2xs">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-rose-600" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="font-bold text-rose-700 hover:text-rose-900 cursor-pointer">
            Dismiss
          </button>
        </div>
      )}

      {/* ============================================================== */}
      {/* INLINE HUMAN-IN-THE-LOOP REVIEW GATE (When Run is Paused)      */}
      {/* ============================================================== */}
      {openReviewTasks.length > 0 && (
        <div className="rounded-2xl border-2 border-amber-300 bg-amber-50/40 p-6 shadow-sm space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-amber-200/80 pb-4">
            <div className="flex items-start gap-3">
              <ShieldAlert className="h-6 w-6 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-base font-bold text-amber-950 flex items-center gap-2">
                  <span>Mandatory Human-in-the-Loop Review Gate</span>
                  <span className="rounded-full bg-amber-200 px-2.5 py-0.5 text-xs font-bold text-amber-900">
                    {openReviewTasks.length} Flagged Item(s)
                  </span>
                </h2>
                <p className="text-xs text-amber-800 mt-1">
                  The LangGraph workflow paused cleanly at a durable SQLite checkpoint. Approve, correct, or reject these items to automatically resume and finalize the audit.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={openBatchApproveModal}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-2 text-xs font-semibold text-white shadow-2xs hover:bg-emerald-700 transition-colors cursor-pointer"
              >
                <CheckCheck className="h-4 w-4" />
                <span>Approve All {openReviewTasks.length} Items</span>
              </button>
            </div>
          </div>

          {/* List of open review tasks for this audit */}
          <div className="space-y-3">
            {openReviewTasks.map((task) => (
              <div
                key={task.task_id}
                className="rounded-xl border border-amber-200 bg-white p-4 shadow-2xs space-y-3 hover:border-amber-300 transition-all"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-900 text-sm">{task.metric_name}</span>
                    <span className="text-[10px] font-mono text-slate-400">({task.task_id})</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openReviewModal(task, 'APPROVE')}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-700 shadow-2xs cursor-pointer"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      <span>Approve</span>
                    </button>
                    <button
                      onClick={() => openReviewModal(task, 'CORRECT')}
                      className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700 shadow-2xs cursor-pointer"
                    >
                      <Edit3 className="h-3 w-3" />
                      <span>Correct</span>
                    </button>
                    <button
                      onClick={() => openReviewModal(task, 'REJECT')}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50 cursor-pointer"
                    >
                      <XCircle className="h-3 w-3" />
                      <span>Reject</span>
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                  <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                    <span className="text-[10px] text-slate-500 block">Extracted Decimal</span>
                    <span className="font-mono text-xs font-bold text-slate-900 block mt-0.5">
                      {formatWorkspaceCurrency(task.normalized_decimal || task.raw_value, task.unit || 'USD')}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400 block truncate">
                      {task.normalized_decimal || task.raw_value}
                    </span>
                  </div>

                  <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                    <span className="text-[10px] text-slate-500 block">Confidence Score</span>
                    <span className="font-mono text-xs font-bold text-amber-700 block mt-0.5">
                      {task.confidence_score !== null ? `${(task.confidence_score! * 100).toFixed(1)}%` : 'N/A'}{' '}
                      <span className="text-[10px] font-normal text-slate-400">(cutoff: 80%)</span>
                    </span>
                  </div>

                  <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200">
                    <span className="text-[10px] text-amber-800 font-bold block">Escalation Reason</span>
                    <span className="text-[11px] text-amber-900 block mt-0.5 truncate" title={task.reason}>
                      {task.reason}
                    </span>
                  </div>
                </div>

                {task.source_evidence && (
                  <div className="rounded-lg bg-slate-50 p-2.5 border border-slate-200 text-xs font-mono text-[11px] text-slate-700 italic">
                    "{task.source_evidence}"
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* PROMINENT OVERALL CONFIDENCE SCORE SECTION */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs space-y-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Deterministic Overall Confidence
            </span>
            <div className="flex items-baseline gap-3">
              <span className="text-5xl font-serif font-bold text-slate-950 tracking-tight">
                {confidencePercent}%
              </span>
              <span
                className={`rounded-full px-3 py-1 text-xs font-bold ${
                  isHighConfidence
                    ? 'bg-emerald-100 text-emerald-800'
                    : isMediumConfidence
                    ? 'bg-amber-100 text-amber-800'
                    : 'bg-rose-100 text-rose-800'
                }`}
              >
                {isHighConfidence
                  ? 'High Confidence (>= 90%)'
                  : isMediumConfidence
                  ? 'Review Recommended (60% - 90%)'
                  : 'Escalation Required (< 60%)'}
              </span>
            </div>
            <p className="text-xs text-slate-500 max-w-xl pt-1">
              Deterministic 5-factor additive confidence score calculated across XBRL taxonomy concepts, duration alignment, unit scale, and SEC tabular cross-referencing.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowMethodology(!showMethodology)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors cursor-pointer"
            >
              <span>Methodology & Weights</span>
              {showMethodology ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {/* Confidence Progress Bar */}
        <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
          <div
            className={`h-2.5 rounded-full transition-all duration-500 ${
              isHighConfidence ? 'bg-emerald-500' : isMediumConfidence ? 'bg-amber-500' : 'bg-rose-500'
            }`}
            style={{ width: `${Math.min(confidenceValue * 100, 100)}%` }}
          />
        </div>

        {/* Collapsible Methodology Section */}
        {showMethodology && (
          <div className="border-t border-slate-200 pt-5 space-y-4">
            <div className="text-xs font-semibold text-slate-900">
              5-Factor Additive Scoring Weights (v1.0.0)
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                <div className="text-xs font-semibold text-slate-800">Concept Match</div>
                <div className="text-lg font-bold text-blue-600 mt-1">25%</div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  US-GAAP standard taxonomy alignment.
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                <div className="text-xs font-semibold text-slate-800">Period Alignment</div>
                <div className="text-lg font-bold text-blue-600 mt-1">25%</div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  10-K fiscal year duration match.
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                <div className="text-xs font-semibold text-slate-800">Unit & Scale</div>
                <div className="text-lg font-bold text-blue-600 mt-1">20%</div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  Exact Decimal & multiplier verification.
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                <div className="text-xs font-semibold text-slate-800">Evidence Quality</div>
                <div className="text-lg font-bold text-blue-600 mt-1">20%</div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  Verifiable SEC accession & chunk citation.
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
                <div className="text-xs font-semibold text-slate-800">Path Agreement</div>
                <div className="text-lg font-bold text-blue-600 mt-1">10%</div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  Independent cross-source consensus.
                </div>
              </div>
            </div>
            <p className="text-[11px] text-slate-500">
              * Note: In accordance with FinovaLabs auditing principles, any unavailable or unobserved factor receives a strict score of 0.00 rather than an assumed default.
            </p>
          </div>
        )}
      </div>

      {/* EXTRACTED FINANCIAL METRICS & SEC COMPANY FACTS COMPARISON */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 bg-slate-50/50">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Extracted Financial Metrics (8 Standards)</h2>
            <p className="text-xs text-slate-500">
              Audited balance sheet, income statement, and cash flow items normalized with exact Python Decimals.
            </p>
          </div>
          <span className="text-xs font-mono font-medium text-slate-500">
            {metrics.length} metrics recorded
          </span>
        </div>

        {metrics.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-400">
            No metrics extracted yet for this run.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <th className="py-3 px-4 sm:px-6">Standard Metric</th>
                  <th className="py-3 px-4 text-right">Normalized Value</th>
                  <th className="py-3 px-4 text-right">SEC Facts Benchmark</th>
                  <th className="py-3 px-4">Period</th>
                  <th className="py-3 px-4">Unit</th>
                  <th className="py-3 px-4">Evidence</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {metrics.map((m) => {
                  const citation = evidenceList.find((e) => e.metric_name === m.metric_name)
                  const evalItem = report?.evaluations?.find((e) => e.metric_name === m.metric_name)
                  const benchmarkVal = evalItem?.reference_value || (evalItem as any)?.ground_truth_decimal || (evalItem as any)?.ground_truth_value
                  const isFlagged = m.review_status === 'REQUIRED' || m.validation_status === 'FLAGGED'
                  const isCorrected = Boolean(m.reviewed_decimal)

                  return (
                    <tr key={m.metric_name} className="hover:bg-slate-50/60 transition-colors">
                      <td className="py-3.5 px-4 sm:px-6 font-semibold text-slate-900">
                        {m.metric_name}
                      </td>
                      <td className="py-3.5 px-4 text-right font-mono font-bold text-slate-900">
                        {formatWorkspaceCurrency(m.normalized_decimal || m.raw_value, m.unit || 'USD')}
                      </td>
                      <td className="py-3.5 px-4 text-right font-mono text-[11px] text-slate-600">
                        {benchmarkVal ? formatWorkspaceCurrency(benchmarkVal, m.unit || 'USD') : 'SEC Facts'}
                      </td>
                      <td className="py-3.5 px-4 text-slate-600 font-mono text-[11px]">
                        {m.period_end || (m.fiscal_year ? `FY${m.fiscal_year}` : '10-K')}
                      </td>
                      <td className="py-3.5 px-4 text-slate-500 font-mono text-[11px]">
                        {m.unit || 'USD'}
                      </td>
                      <td className="py-3.5 px-4">
                        {citation ? (
                          <button
                            onClick={() => setSelectedEvidence(citation)}
                            className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:text-blue-800 underline cursor-pointer"
                          >
                            <span>SEC Citation</span>
                            <ExternalLink className="h-3 w-3" />
                          </button>
                        ) : (
                          <span className="text-[11px] text-slate-400">Company Facts</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                            isCorrected
                              ? 'bg-purple-50 text-purple-700 ring-1 ring-purple-600/20'
                              : isFlagged
                              ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-600/20'
                              : 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20'
                          }`}
                        >
                          {isFlagged ? (
                            <AlertTriangle className="h-3 w-3" />
                          ) : (
                            <CheckCircle2 className="h-3 w-3" />
                          )}
                          <span>{isCorrected ? 'CORRECTED' : isFlagged ? 'FLAGGED' : 'APPROVED'}</span>
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* VALIDATION INSIGHTS TABLE */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 bg-slate-50/50">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Deterministic Financial Validations</h2>
            <p className="text-xs text-slate-500">
              Accounting equation, YoY variance anomalies, and segment revenue reconciliation checks.
            </p>
          </div>
          <span className="text-xs font-mono font-medium text-slate-500">
            {validations.length} checks executed
          </span>
        </div>

        {validations.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">
            No validations executed yet for this run.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <th className="py-3 px-4 sm:px-6">Validation Rule</th>
                  <th className="py-3 px-4">Line Item / Target</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Audit Explanation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {validations.map((v) => {
                  const isPass = v.status === 'PASS'
                  const isFail = v.status === 'FAIL'
                  const isWarn = v.status === 'WARNING'
                  return (
                    <tr key={v.validation_id} className="hover:bg-slate-50/60">
                      <td className="py-3.5 px-4 sm:px-6 font-semibold text-slate-900">
                        {v.rule_name.replace(/_/g, ' ')}
                      </td>
                      <td className="py-3.5 px-4 text-slate-700">
                        {v.metric_name}
                      </td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                            isPass
                              ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20'
                              : isFail
                              ? 'bg-rose-50 text-rose-700 ring-1 ring-rose-600/20'
                              : isWarn
                              ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-600/20'
                              : 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {v.status}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-slate-600 leading-relaxed font-sans max-w-md">
                        {v.explanation}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* EVIDENCE CITATION MODAL */}
      {selectedEvidence && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <FileCheck2 className="h-5 w-5 text-blue-600" />
                <h3 className="text-base font-bold text-slate-900">
                  SEC Source Evidence Citation
                </h3>
              </div>
              <button
                onClick={() => setSelectedEvidence(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 space-y-3 text-xs">
              <div>
                <span className="font-semibold text-slate-700">Metric Name:</span>{' '}
                <span className="font-bold text-slate-900">{selectedEvidence.metric_name}</span>
              </div>
              {selectedEvidence.evidence_location && (
                <div>
                  <span className="font-semibold text-slate-700">Filing Location:</span>{' '}
                  <span className="font-mono text-slate-800">{selectedEvidence.evidence_location}</span>
                </div>
              )}
              {selectedEvidence.normalized_decimal && (
                <div>
                  <span className="font-semibold text-slate-700">Extracted Decimal Value:</span>{' '}
                  <span className="font-mono text-slate-900 font-bold">{selectedEvidence.normalized_decimal} {selectedEvidence.unit || 'USD'}</span>
                </div>
              )}

              {selectedEvidence.source_evidence && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 mt-3">
                  <span className="font-semibold text-slate-800 block mb-1">Verbatim SEC Excerpt:</span>
                  <p className="font-mono text-[11px] leading-relaxed text-slate-700 italic">
                    "{selectedEvidence.source_evidence}"
                  </p>
                </div>
              )}

              {selectedEvidence.source_url && (
                <div className="pt-2">
                  <a
                    href={selectedEvidence.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-600 hover:underline"
                  >
                    <span>View Official Filing on SEC EDGAR</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                </div>
              )}
            </div>

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setSelectedEvidence(null)}
                className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 cursor-pointer"
              >
                Close Citation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* REVIEW ACTION MODAL (Approve, Correct, Reject, Batch Approve) */}
      {reviewActionType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl space-y-5">
            <div className="border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                {reviewActionType === 'APPROVE' && <CheckCircle2 className="h-5 w-5 text-emerald-600" />}
                {reviewActionType === 'CORRECT' && <Edit3 className="h-5 w-5 text-blue-600" />}
                {reviewActionType === 'REJECT' && <XCircle className="h-5 w-5 text-rose-600" />}
                {reviewActionType === 'BATCH_APPROVE' && <CheckCheck className="h-5 w-5 text-emerald-600" />}

                {reviewActionType === 'APPROVE' && 'Approve Extracted Metric Value'}
                {reviewActionType === 'CORRECT' && 'Correct Extracted Metric Value'}
                {reviewActionType === 'REJECT' && 'Reject Extracted Metric Value'}
                {reviewActionType === 'BATCH_APPROVE' && 'Batch Approve All Flagged Items'}
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                {reviewActionType === 'BATCH_APPROVE' ? (
                  <span>
                    Confirm approval for all {openReviewTasks.length} pending review items for this audit.
                  </span>
                ) : (
                  <span>
                    Target: <span className="font-bold text-slate-800">{selectedReviewTask?.metric_name}</span> ({selectedReviewTask?.task_id})
                  </span>
                )}
              </p>
            </div>

            <form onSubmit={handleReviewDecisionSubmit} className="space-y-4">
              {/* Highlight original value for single task */}
              {selectedReviewTask && (
                <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-xs">
                  <div className="text-slate-500 text-[11px]">Original Extracted Amount:</div>
                  <div className="text-sm font-bold font-mono text-slate-900 mt-0.5">
                    {formatWorkspaceCurrency(selectedReviewTask.normalized_decimal || selectedReviewTask.raw_value, selectedReviewTask.unit || 'USD')}
                    <span className="text-xs font-normal text-slate-500 ml-2">
                      ({selectedReviewTask.normalized_decimal || selectedReviewTask.raw_value})
                    </span>
                  </div>
                </div>
              )}

              {reviewActionType === 'CORRECT' && (
                <div>
                  <label className="block text-xs font-semibold text-slate-800 mb-1">
                    Revised Normalized Value (Exact Python Decimal) <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={reviewCorrectedVal}
                    onChange={(e) => setReviewCorrectedVal(e.target.value)}
                    placeholder="e.g. 391035000000"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono font-bold text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    required
                  />
                  {reviewCorrectedVal && (
                    <span className="text-[11px] text-blue-700 font-mono block mt-1">
                      Formatted Preview: {formatWorkspaceCurrency(reviewCorrectedVal, selectedReviewTask?.unit || 'USD')}
                    </span>
                  )}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-800 mb-1">
                  Audit Justification Note {reviewActionType !== 'APPROVE' && reviewActionType !== 'BATCH_APPROVE' && <span className="text-rose-500">*</span>}
                </label>
                <textarea
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  placeholder={
                    reviewActionType === 'APPROVE' || reviewActionType === 'BATCH_APPROVE'
                      ? 'Analyst audit notes for record-keeping...'
                      : 'Provide verifiable explanation and SEC 10-K citation for this decision...'
                  }
                  rows={3}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  required={reviewActionType === 'CORRECT' || reviewActionType === 'REJECT'}
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
                  onClick={closeReviewModal}
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submittingReviewAction}
                  className={`rounded-lg px-5 py-2 text-xs font-semibold text-white transition-colors cursor-pointer ${
                    reviewActionType === 'APPROVE' || reviewActionType === 'BATCH_APPROVE'
                      ? 'bg-emerald-600 hover:bg-emerald-700'
                      : reviewActionType === 'CORRECT'
                      ? 'bg-blue-600 hover:bg-blue-700'
                      : 'bg-rose-600 hover:bg-rose-700'
                  }`}
                >
                  {submittingReviewAction
                    ? 'Recording Decision...'
                    : reviewActionType === 'BATCH_APPROVE'
                    ? 'Confirm Batch Approval'
                    : `Confirm ${reviewActionType}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
