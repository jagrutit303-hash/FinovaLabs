import React, { useEffect, useState } from 'react'
import {
  ShieldCheck,
  Save,
  CheckCircle2,
  Cpu,
  Server,
  RotateCcw,
} from 'lucide-react'
import { api } from '../api/client'
import type { SettingsData, HealthResponse } from '../api/client'

export const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [saving, setSaving] = useState<boolean>(false)
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Form states
  const [autoApprove, setAutoApprove] = useState<number>(0.90)
  const [reviewRequired, setReviewRequired] = useState<number>(0.60)
  const [accountingTolerance, setAccountingTolerance] = useState<number>(0.0005)
  const [segmentTolerance, setSegmentTolerance] = useState<number>(0.02)
  const [yoyThreshold, setYoyThreshold] = useState<number>(0.30)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.getSettings(),
      api.getHealth().catch(() => null),
    ])
      .then(([setData, healthData]) => {
        setSettings(setData)
        setHealth(healthData)
        setAutoApprove(setData.auto_approve_threshold)
        setReviewRequired(setData.review_required_threshold)
        setAccountingTolerance(setData.accounting_identity_tolerance)
        setSegmentTolerance(setData.segment_reconciliation_tolerance)
        setYoyThreshold(setData.yoy_change_alert_threshold)
      })
      .catch((err: any) => {
        setErrorMessage(err.message || 'Failed to load system settings.')
      })
      .finally(() => setLoading(false))
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSaveSuccess(false)
    setErrorMessage(null)

    if (autoApprove <= reviewRequired) {
      setErrorMessage('Auto-approve threshold must be strictly greater than review-required threshold.')
      setSaving(false)
      return
    }

    try {
      const updated = await api.updateSettings({
        auto_approve_threshold: Number(autoApprove),
        review_required_threshold: Number(reviewRequired),
        accounting_identity_tolerance: Number(accountingTolerance),
        segment_reconciliation_tolerance: Number(segmentTolerance),
        yoy_change_alert_threshold: Number(yoyThreshold),
      })
      setSettings(updated)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 4000)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="py-20 text-center text-xs text-slate-400">
        <RotateCcw className="h-7 w-7 text-blue-600 animate-spin mx-auto mb-2" />
        Loading system configuration...
      </div>
    )
  }

  return (
    <div className="py-8 px-4 sm:px-6 lg:px-8 max-w-4xl mx-auto space-y-8">
      {/* Page Title */}
      <div className="border-b border-slate-200 pb-5">
        <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">
          Governance & Pipeline Configuration
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Manage explainable confidence cutoffs, reconciliation tolerance limits, and inspect SQLite persistence.
        </p>
      </div>

      {saveSuccess && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-xs font-medium text-emerald-900 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          <span>Configuration thresholds successfully updated in backend memory.</span>
        </div>
      )}

      {errorMessage && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-800">
          {errorMessage}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Confidence Thresholds */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-5">
          <div className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-blue-600" />
            <h2 className="text-base font-semibold text-slate-900">Confidence Scoring Thresholds</h2>
          </div>
          <p className="text-xs text-slate-500">
            Determine when extracted financial metrics are automatically approved vs escalated to human reviewers.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <div>
              <label className="block text-xs font-semibold text-slate-800 mb-1">
                Auto-Approve Cutoff (Currently {(autoApprove * 100).toFixed(0)}%)
              </label>
              <input
                type="number"
                step="0.01"
                min="0.50"
                max="1.00"
                value={autoApprove}
                onChange={(e) => setAutoApprove(parseFloat(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Metrics scoring at or above this threshold skip manual review.
              </span>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-800 mb-1">
                Review Required Cutoff (Currently {(reviewRequired * 100).toFixed(0)}%)
              </label>
              <input
                type="number"
                step="0.01"
                min="0.00"
                max="0.89"
                value={reviewRequired}
                onChange={(e) => setReviewRequired(parseFloat(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Scores below this threshold trigger mandatory human escalation.
              </span>
            </div>
          </div>
        </div>

        {/* Validation Tolerances */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-5">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-emerald-600" />
            <h2 className="text-base font-semibold text-slate-900">Financial Validation Tolerances</h2>
          </div>
          <p className="text-xs text-slate-500">
            Configure acceptable rounding discrepancy boundaries for accounting identities and YoY alerts.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
            <div>
              <label className="block text-xs font-semibold text-slate-800 mb-1">
                Identity Tolerance
              </label>
              <input
                type="number"
                step="0.0001"
                value={accountingTolerance}
                onChange={(e) => setAccountingTolerance(parseFloat(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Assets = Liabilities + Equity (default 0.05%)
              </span>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-800 mb-1">
                Segment Tolerance
              </label>
              <input
                type="number"
                step="0.005"
                value={segmentTolerance}
                onChange={(e) => setSegmentTolerance(parseFloat(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Segment sum vs consolidated revenue (default 2%)
              </span>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-800 mb-1">
                YoY Alert Threshold
              </label>
              <input
                type="number"
                step="0.05"
                value={yoyThreshold}
                onChange={(e) => setYoyThreshold(parseFloat(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono text-slate-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                required
              />
              <span className="text-[11px] text-slate-400 mt-1 block">
                Flag variance exceeding threshold (default 30%)
              </span>
            </div>
          </div>
        </div>

        {/* Confidence Weights (Read-only distribution display) */}
        {settings && (
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
            <h2 className="text-base font-semibold text-slate-900">Confidence Factor Weights (Fixed)</h2>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 pt-1">
              {Object.entries(settings.confidence_weights).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-slate-50 p-3 border border-slate-100">
                  <span className="text-[11px] font-semibold text-slate-600 capitalize block">
                    {k.replace(/_/g, ' ')}
                  </span>
                  <span className="text-lg font-bold font-mono text-blue-600 mt-1 block">
                    {(v * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Save Button */}
        <div className="flex justify-end pt-2">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-xs font-semibold text-white shadow-xs hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? <RotateCcw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            <span>Save Configuration</span>
          </button>
        </div>
      </form>

      {/* System Diagnostics & Environment */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
        <div className="flex items-center gap-2">
          <Server className="h-5 w-5 text-slate-700" />
          <h2 className="text-base font-semibold text-slate-900">System Diagnostics & Environment</h2>
        </div>

        <div className="space-y-2.5 text-xs pt-1">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between py-2 border-b border-slate-100 gap-1">
            <span className="font-medium text-slate-600">SQLite Database Path:</span>
            <span className="font-mono text-slate-900 bg-slate-50 px-2 py-0.5 rounded border border-slate-200 break-all">
              {health?.db_path || settings?.db_path || 'data/finova_labs.db'}
            </span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between py-2 border-b border-slate-100 gap-1">
            <span className="font-medium text-slate-600">SEC EDGAR Cache Directory:</span>
            <span className="font-mono text-slate-900 bg-slate-50 px-2 py-0.5 rounded border border-slate-200 break-all">
              {settings?.sec_cache_dir || 'data/cache/sec'}
            </span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between py-2 border-b border-slate-100 gap-1">
            <span className="font-medium text-slate-600">SEC Client User-Agent Header:</span>
            <span className="font-mono text-slate-900 bg-slate-50 px-2 py-0.5 rounded border border-slate-200">
              {settings?.sec_user_agent || 'FinovaLabs contact@example.com'}
            </span>
          </div>

          <div className="flex items-center justify-between py-2">
            <span className="font-medium text-slate-600">Active Pipeline Version:</span>
            <span className="font-mono font-bold text-blue-700">v{settings?.version || '1.0.0'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
