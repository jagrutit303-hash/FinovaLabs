/**
 * FinovaLabs Frontend API Client
 * Robust client communicating with Python FastAPI backend endpoints.
 */

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (typeof window !== 'undefined' ? '' : 'http://127.0.0.1:8000');

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err: any) {
    // If relative fetch failed (e.g. running on non-proxied port like 5174), retry direct backend
    if (!API_BASE && typeof window !== 'undefined') {
      try {
        const fallbackUrl = `http://127.0.0.1:8000${endpoint}`;
        response = await fetch(fallbackUrl, { ...options, headers });
      } catch {
        throw new Error(err?.message || 'Network error: could not connect to FinovaLabs backend.');
      }
    } else {
      throw new Error(err?.message || 'Network error: could not connect to FinovaLabs backend.');
    }
  }

  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status}`;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore json parse error on response failure
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export interface HealthResponse {
  status: string;
  healthy: boolean;
  sqlite_version?: string;
  table_counts: Record<string, number>;
  missing_tables: string[];
  db_path: string;
  version: string;
}

export interface DashboardSummary {
  total_runs: number;
  total_filings: number;
  open_reviews: number;
  resolved_reviews: number;
  failed_validations: number;
  audit_events: number;
}

export interface Company {
  company_id: string;
  ticker: string;
  cik?: string | null;
  company_name: string;
  display_name: string;
}

export interface Filing {
  id?: number | null;
  cik: string;
  ticker?: string | null;
  company_name?: string | null;
  accession_number: string;
  form_type: string;
  filing_date: string;
  reporting_period?: string | null;
  fiscal_year?: number | null;
  retrieval_status: string;
  filing_url?: string | null;
  fetched_at?: string | null;
}

export interface AuditRun {
  run_id: string;
  ticker?: string | null;
  accession_number?: string | null;
  fiscal_year?: number | null;
  status: string;
  current_step?: string | null;
  overall_confidence?: number | null;
  confidence_category?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  reused_existing_run?: boolean;
  thread_id?: string | null;
}

export interface ExtractedMetric {
  metric_id?: number | null;
  run_id?: string | null;
  metric_name: string;
  raw_value: string;
  normalized_decimal: string;
  unit?: string | null;
  fiscal_period?: string | null;
  fiscal_year?: number | null;
  period_start?: string | null;
  period_end?: string | null;
  source_url?: string | null;
  source_evidence?: string | null;
  evidence_location?: string | null;
  extraction_status?: string | null;
  confidence_score?: number | null;
  validation_status?: string | null;
  review_status?: string | null;
  reviewed_decimal?: string | null;
}

export interface ValidationResult {
  validation_id: string;
  run_id?: string | null;
  cik?: string | null;
  ticker?: string | null;
  accession_number?: string | null;
  rule_name: string;
  metric_name: string;
  status: string;
  explanation: string;
  expected_value?: string | null;
  actual_value?: string | null;
  variance_abs?: string | null;
  variance_pct?: string | null;
  tolerance_used?: string | null;
  escalated?: boolean;
}

export interface EvidenceCitation {
  metric_name: string;
  raw_value?: string | null;
  normalized_decimal?: string | null;
  unit?: string | null;
  source_evidence?: string | null;
  evidence_location?: string | null;
  source_url?: string | null;
  extraction_status?: string | null;
}

export interface ReviewTask {
  task_id: string;
  run_id?: string | null;
  ticker?: string | null;
  company_name?: string | null;
  accession_number?: string | null;
  metric_name: string;
  reason: string;
  status: string;
  raw_value?: string | null;
  normalized_decimal?: string | null;
  unit?: string | null;
  source_evidence?: string | null;
  evidence_location?: string | null;
  confidence_score?: number | null;
  confidence_threshold?: number | null;
  reviewer_note?: string | null;
  resolved_decimal?: string | null;
  resolved_by?: string | null;
  created_at: string;
  resolved_at?: string | null;
}

export interface AccuracyEvaluation {
  metric_name: string;
  extracted_value?: string;
  reference_value?: string;
  matched?: boolean;
  pre_exact_match?: boolean;
  post_exact_match?: boolean;
  discrepancy?: string;
  concept?: string;
}

export interface AuditReport {
  run_id: string;
  ticker?: string | null;
  company_name?: string | null;
  accession_number?: string | null;
  pre_review_accuracy: number;
  post_review_accuracy: number;
  evaluated_metrics_count: number;
  matched_metrics_count: number;
  coverage_denominator: number;
  evaluations: AccuracyEvaluation[];
}

export interface AuditEvent {
  event_id: number;
  seq_id?: number | null;
  run_id?: string | null;
  ticker?: string | null;
  company_name?: string | null;
  metric_name?: string | null;
  event_type: string;
  decision?: string | null;
  original_value?: string | null;
  corrected_value?: string | null;
  actor: string;
  explanation?: string | null;
  prev_hash: string;
  event_hash: string;
  created_at: string;
}

export interface AuditChainVerificationResponse {
  chain_valid: boolean;
  total_events: number;
  reason?: string | null;
}

export interface SettingsData {
  app_name: string;
  version: string;
  auto_approve_threshold: number;
  review_required_threshold: number;
  accounting_identity_tolerance: number;
  segment_reconciliation_tolerance: number;
  yoy_change_alert_threshold: number;
  confidence_weights: Record<string, number>;
  sec_cache_dir: string;
  sec_user_agent: string;
  db_path: string;
}

export interface PerformanceSeriesPoint {
  period: string;
  date: string;
  value: number;
  formatted_value: string;
  unit: string;
  scale: string;
  is_current: boolean;
}

export interface PerformanceMetricSeries {
  metric_name: string;
  display_name: string;
  category: string;
  current_value: number | null;
  current_formatted: string;
  previous_value: number | null;
  previous_formatted: string;
  yoy_change_pct: number | null;
  yoy_change_formatted: string;
  unit: string;
  series: PerformanceSeriesPoint[];
}

export interface VarianceAnalysisItem {
  metric_name: string;
  current_period: string;
  previous_period: string;
  current_value: number | null;
  current_formatted: string;
  previous_value: number | null;
  previous_formatted: string;
  absolute_difference: number | null;
  absolute_difference_formatted: string;
  percentage_difference: number | null;
  percentage_difference_formatted: string;
  is_anomaly: boolean;
  anomaly_status: string;
  threshold_pct: number;
  explanation: string;
  evidence_quote?: string | null;
  evidence_location?: string | null;
  source_url?: string | null;
  xbrl_concept?: string | null;
  scale_factor: number;
  review_status: string;
  validation_status: string;
}

export interface AccountingValidationEquation {
  reporting_period: string;
  assets_value: number | null;
  assets_formatted: string;
  liabilities_value: number | null;
  liabilities_formatted: string;
  equity_value: number | null;
  equity_formatted: string;
  calculated_sum: number | null;
  calculated_sum_formatted: string;
  difference: number | null;
  difference_formatted: string;
  status: 'PASS' | 'FAIL' | 'NOT_APPLICABLE' | 'INDETERMINATE' | string;
  tolerance_applied: string;
  explanation: string;
  has_segment_data: boolean;
  segment_status: string;
  segment_explanation: string;
}

export interface GroundTruthComparisonItem {
  metric_name: string;
  extracted_value: number | null;
  extracted_formatted: string;
  reference_value: number | null;
  reference_formatted: string;
  absolute_difference: number | null;
  absolute_difference_formatted: string;
  percentage_difference: number | null;
  percentage_difference_formatted: string;
  unit_compatible: boolean;
  extracted_unit: string;
  reference_unit: string;
  period_compatible: boolean;
  extracted_period: string;
  reference_period: string;
  match_status: 'MATCHED' | 'VARIANCE' | 'INCOMPATIBLE_PERIOD' | 'INCOMPATIBLE_UNIT' | string;
  concept: string;
  reference_url?: string | null;
}

export interface AuditConfidenceAndCoverage {
  overall_confidence: number;
  confidence_percent: number;
  confidence_category: 'HIGH' | 'MEDIUM_REVIEW' | 'LOW_ESCALATE' | string;
  coverage_count: number;
  coverage_required: number;
  coverage_percent: number;
  validation_failures_count: number;
  validation_warnings_count: number;
  pending_reviews_count: number;
  methodology_weights: Record<string, number>;
}

export interface HumanReviewAnalytics {
  total_reviews: number;
  approved_count: number;
  corrected_count: number;
  rejected_count: number;
  pending_count: number;
  escalation_reasons: { reason: string; count: number }[];
  pre_review_accuracy: number;
  post_review_accuracy: number;
  governance_notice: string;
}

export interface AuditAnalyticsDetailResponse {
  run_id: string;
  ticker: string;
  company_name: string;
  fiscal_year?: number | null;
  status: string;
  performance_metrics: PerformanceMetricSeries[];
  variance_items: VarianceAnalysisItem[];
  accounting_equation: AccountingValidationEquation;
  ground_truth_items: GroundTruthComparisonItem[];
  confidence_coverage: AuditConfidenceAndCoverage;
  human_review_analytics: HumanReviewAnalytics;
}

export interface AnalyticsOptionsResponse {
  runs: {
    run_id: string;
    ticker: string;
    company_name: string;
    fiscal_year?: number | null;
    status: string;
    overall_confidence?: number | null;
  }[];
  companies: {
    ticker: string;
    company_name: string;
  }[];
}

export const api = {
  // Health & Summary
  getHealth: () => request<HealthResponse>('/api/health'),
  getSummary: () => request<DashboardSummary>('/api/dashboard/summary'),

  // Companies & Filings
  getCompanies: (query?: string) =>
    request<Company[]>(query ? `/api/companies?q=${encodeURIComponent(query)}` : '/api/companies'),
  getCompanyFilings: (companyId: string) => request<Filing[]>(`/api/companies/${encodeURIComponent(companyId)}/filings`),

  // Audits
  createAudit: (payload: { ticker?: string; cik?: string; accession_number?: string; force_reprocess?: boolean }) =>
    request<AuditRun>('/api/audits', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getAudits: (statusFilter?: string) => {
    const q = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : '';
    return request<AuditRun[]>(`/api/audits${q}`);
  },
  getAudit: (auditId: string) => request<AuditRun>(`/api/audits/${encodeURIComponent(auditId)}`),
  getAuditResults: (auditId: string) => request<ExtractedMetric[]>(`/api/audits/${encodeURIComponent(auditId)}/results`),
  getAuditValidations: (auditId: string) => request<ValidationResult[]>(`/api/audits/${encodeURIComponent(auditId)}/validations`),
  getAuditEvidence: (auditId: string) => request<EvidenceCitation[]>(`/api/audits/${encodeURIComponent(auditId)}/evidence`),
  resumeAudit: (auditId: string) =>
    request<AuditRun>(`/api/audits/${encodeURIComponent(auditId)}/resume`, {
      method: 'POST',
    }),
  getAuditReport: (auditId: string) => request<AuditReport>(`/api/audits/${encodeURIComponent(auditId)}/report`),
  getAuditHistory: (auditId: string) => request<AuditEvent[]>(`/api/audits/${encodeURIComponent(auditId)}/history`),
  verifyAuditChain: () => request<AuditChainVerificationResponse>('/api/audit-trail/verify'),

  // Reviews
  getReviews: (statusFilter?: string, runId?: string) => {
    const params = new URLSearchParams();
    if (statusFilter) {
      params.append('status', statusFilter);
      params.append('status_filter', statusFilter);
    }
    if (runId) params.append('run_id', runId);
    const q = params.toString() ? `?${params.toString()}` : '';
    return request<ReviewTask[]>(`/api/reviews${q}`);
  },
  getReview: (reviewId: string) => request<ReviewTask>(`/api/reviews/${encodeURIComponent(reviewId)}`),
  batchApproveReviews: (taskIds: string[], data: { notes?: string; note?: string; reviewer?: string } = {}) =>
    request<{ approved_count: number; remaining_open_tasks: number; resumed_workflow_status?: string; resumed_run_id?: string }>('/api/reviews/batch-approve', {
      method: 'POST',
      body: JSON.stringify({
        task_ids: taskIds,
        reviewer: data.reviewer || 'analyst',
        note: data.note || data.notes || '',
        auto_resume: true,
      }),
    }),
  approveReview: (reviewId: string, data: { notes?: string; note?: string; reviewer?: string } = {}) =>
    request<any>(`/api/reviews/${encodeURIComponent(reviewId)}/approve`, {
      method: 'POST',
      body: JSON.stringify({
        reviewer: data.reviewer || 'analyst',
        note: data.note || data.notes || '',
        notes: data.notes || data.note || '',
        auto_resume: true,
      }),
    }),
  correctReview: (reviewId: string, data: { corrected_value: string; notes?: string; note?: string; reviewer?: string }) =>
    request<any>(`/api/reviews/${encodeURIComponent(reviewId)}/correct`, {
      method: 'POST',
      body: JSON.stringify({
        corrected_value: data.corrected_value,
        reviewer: data.reviewer || 'analyst',
        note: data.note || data.notes || '',
        notes: data.notes || data.note || '',
        auto_resume: true,
      }),
    }),
  rejectReview: (reviewId: string, data: { reason?: string; notes?: string; note?: string; reviewer?: string }) =>
    request<any>(`/api/reviews/${encodeURIComponent(reviewId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({
        reviewer: data.reviewer || 'analyst',
        note: data.note || data.notes || data.reason || '',
        notes: data.notes || data.note || data.reason || '',
        reason: data.reason || data.note || data.notes || '',
        auto_resume: true,
      }),
    }),

  // Analytics
  getAnalyticsOptions: () => request<AnalyticsOptionsResponse>('/api/analytics/options'),
  getAuditAnalytics: (auditId: string) =>
    request<AuditAnalyticsDetailResponse>(`/api/analytics/audit/${encodeURIComponent(auditId)}`),

  // Settings
  getSettings: () => request<SettingsData>('/api/settings'),
  updateSettings: (data: Partial<SettingsData>) =>
    request<SettingsData>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
};

