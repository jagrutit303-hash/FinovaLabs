import React from 'react'
import {
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  Layers,
  Sparkles,
  Clock,
  UserCheck,
} from 'lucide-react'

interface Hero66Props {
  onStartAudit: () => void
  onExploreHowItWorks: () => void
}

export const Hero66: React.FC<Hero66Props> = ({
  onStartAudit,
  onExploreHowItWorks,
}) => {
  return (
    <section className="relative overflow-hidden bg-slate-900 pt-16 pb-24 text-white lg:pt-24 lg:pb-32">
      {/* Background Radial Glow & Grid Pattern */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(37,99,235,0.25),rgba(255,255,255,0))]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-25" />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col items-center text-center">
          {/* Announcement / Status Pill */}
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-950/60 px-3.5 py-1.5 text-xs font-medium text-blue-300 shadow-inner backdrop-blur-md">
            <span className="flex h-2 w-2 rounded-full bg-blue-400 animate-pulse" />
            <span className="font-semibold text-blue-200">MINEARENA 1.0 PS-01</span>
            <span className="text-slate-400">•</span>
            <span>AI-Powered Financial Filing Auditor</span>
            <ArrowRight className="h-3 w-3 text-blue-400" />
          </div>

          {/* Primary Headline */}
          <h1 className="mt-8 max-w-4xl font-serif text-4xl font-bold tracking-tight text-white sm:text-6xl sm:leading-[1.12]">
            Financial intelligence.{' '}
            <span className="bg-gradient-to-r from-blue-400 via-sky-300 to-indigo-300 bg-clip-text text-transparent">
              Auditing with confidence.
            </span>
          </h1>

          {/* Product Introduction Paragraph */}
          <p className="mt-6 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
            An evidence-first financial filing auditor that extracts, validates and reviews SEC financial information while preserving every important decision.
          </p>

          {/* Primary & Secondary Action CTAs */}
          <div className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center">
            <button
              onClick={onStartAudit}
              className="group inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-blue-600/30 transition-all hover:bg-blue-500 hover:shadow-blue-500/40 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-slate-900"
            >
              <span>Start an Audit</span>
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </button>
            <button
              onClick={onExploreHowItWorks}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800/80 px-7 py-3.5 text-base font-medium text-slate-200 backdrop-blur-sm transition-all hover:border-slate-600 hover:bg-slate-700/80 hover:text-white focus:outline-none focus:ring-2 focus:ring-slate-500"
            >
              <Layers className="h-4 w-4 text-blue-400" />
              <span>Explore How It Works</span>
            </button>
          </div>

          {/* Key Architectural Highlights / Trust Bar */}
          <div className="mt-14 grid grid-cols-2 gap-4 border-t border-slate-800/80 pt-10 sm:grid-cols-4 sm:gap-8">
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-white sm:text-3xl">5 Equities</span>
              <span className="mt-1 text-xs text-slate-400 sm:text-sm">AAPL, MSFT, GOOGL, AMZN, WMT</span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-blue-400 sm:text-3xl">Exact Decimal</span>
              <span className="mt-1 text-xs text-slate-400 sm:text-sm">Zero Rounding Drift & Signs</span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-emerald-400 sm:text-3xl">90% Cutoff</span>
              <span className="mt-1 text-xs text-slate-400 sm:text-sm">5-Factor Additive Confidence</span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-indigo-400 sm:text-3xl">SHA-256</span>
              <span className="mt-1 text-xs text-slate-400 sm:text-sm">Append-Only Audit Chain</span>
            </div>
          </div>

          {/* Hero Visual Mockup: FinovaLabs Live Audit Console */}
          <div className="mt-14 w-full max-w-5xl rounded-2xl border border-slate-700/80 bg-slate-950/90 p-2 shadow-2xl shadow-blue-900/30 backdrop-blur-xl ring-1 ring-white/10 sm:p-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 sm:p-6 text-left">
              {/* Window Header */}
              <div className="flex flex-wrap items-center justify-between border-b border-slate-800 pb-4 gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex gap-1.5">
                    <span className="h-3 w-3 rounded-full bg-rose-500/80" />
                    <span className="h-3 w-3 rounded-full bg-amber-500/80" />
                    <span className="h-3 w-3 rounded-full bg-emerald-500/80" />
                  </div>
                  <span className="rounded bg-slate-800 px-2.5 py-1 font-mono text-xs text-slate-300">
                    audit_run: aapl-fy2024-sec10k
                  </span>
                  <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400 border border-emerald-500/20">
                    Live SEC EDGAR Ingested
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Clock className="h-3.5 w-3.5 text-slate-500" />
                  <span>Checkpointed via LangGraph SqliteSaver</span>
                </div>
              </div>

              {/* Console Metrics Grid */}
              <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="rounded-lg border border-slate-800/80 bg-slate-950/50 p-4">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Revenue (Net Sales)</span>
                    <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-400">
                      98.0% Pass
                    </span>
                  </div>
                  <div className="mt-2 text-2xl font-bold text-white">$391,035,000,000</div>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-400">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                    <span>Table 1, Row 1 (Auto-Approved)</span>
                  </div>
                </div>

                <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-4">
                  <div className="flex items-center justify-between text-xs text-amber-300">
                    <span>Net Income</span>
                    <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[11px] font-semibold text-amber-300">
                      77.0% Flagged
                    </span>
                  </div>
                  <div className="mt-2 text-2xl font-bold text-white">$93,736,000,000</div>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-amber-300">
                    <UserCheck className="h-3.5 w-3.5 text-amber-400" />
                    <span>Review Required: Below 90% Threshold</span>
                  </div>
                </div>

                <div className="rounded-lg border border-slate-800/80 bg-slate-950/50 p-4">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Balance Sheet Identity</span>
                    <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-400">
                      Passed
                    </span>
                  </div>
                  <div className="mt-2 text-xl font-bold text-white">Assets = Liab + Equity</div>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-400">
                    <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                    <span>Tolerance ≤ 0.05% Verified</span>
                  </div>
                </div>
              </div>

              {/* Console Live Action Banner */}
              <div className="mt-4 flex flex-wrap items-center justify-between rounded-lg bg-blue-950/40 border border-blue-800/40 px-4 py-3 text-xs sm:text-sm">
                <div className="flex items-center gap-2 text-blue-200">
                  <Sparkles className="h-4 w-4 text-blue-400 shrink-0" />
                  <span>
                    <strong>Next Action:</strong> Resolve 1 flagged item in Review Center or verify SHA-256 audit chain.
                  </span>
                </div>
                <button
                  onClick={onStartAudit}
                  className="mt-2 sm:mt-0 font-medium text-blue-400 hover:text-blue-300 underline underline-offset-4"
                >
                  Open in Workspace &rarr;
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
