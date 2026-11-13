import React from 'react'
import {
  Database,
  Cpu,
  ShieldCheck,
  FileSearch,
  Lock,
  GitBranch,
  Terminal,
  ExternalLink,
} from 'lucide-react'

export const BackendPillars: React.FC = () => {
  const pillars = [
    {
      title: '1. SEC EDGAR Ingestion',
      module: 'sec_client.py',
      description:
        'Rate-limited HTTP client (<=10 req/s) with exponential retries, User-Agent enforcement, and offline caching under data/cache/sec/. Supports 5 US equities.',
      icon: FileSearch,
      tone: 'blue',
    },
    {
      title: '2. LangGraph State Machine',
      module: 'workflow.py',
      description:
        'Durable execution graph powered by LangGraph and SqliteSaver. Pauses execution cleanly on low confidence or validation failures via interrupt().',
      icon: GitBranch,
      tone: 'indigo',
    },
    {
      title: '3. Durable SQLite Persistence',
      module: 'database.py',
      description:
        '8 relational core tables in WAL mode with foreign keys, schema migrations, and idempotency key guards to guarantee zero duplicate actions on recovery.',
      icon: Database,
      tone: 'emerald',
    },
    {
      title: '4. 5-Factor Confidence Scoring',
      module: 'confidence.py',
      description:
        'Additive model scoring Concept Match (25%), Period Match (25%), Unit/Scale (20%), Evidence (20%), and Cross-Path Agreement (10%). Unavailable factors score 0.00.',
      icon: Cpu,
      tone: 'amber',
    },
    {
      title: '5. Mandatory Human-in-the-Loop',
      module: 'views.py / workflow.py',
      description:
        'Analysts approve, edit, or reject escalated items. Human review decisions commit atomically to SQLite before the workflow is allowed to resume.',
      icon: ShieldCheck,
      tone: 'purple',
    },
    {
      title: '6. Tamper-Evident Audit Ledger',
      module: 'audit.py',
      description:
        'Append-only cryptographic SHA-256 hash chain with sequential seq_id and previous-hash verification. Detects row modifications or deletions instantly.',
      icon: Lock,
      tone: 'slate',
    },
  ]

  return (
    <section id="how-it-works" className="py-20 bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <span className="text-xs font-semibold uppercase tracking-wider text-blue-600">
            Existing Python Backend Architecture
          </span>
          <h2 className="mt-2 font-serif text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
            Real Financial Engineering Under the Hood
          </h2>
          <p className="mt-4 text-base text-slate-600">
            The React landing page provides an executive interface and visual tour, while FinovaLabs' Python backend handles authentic SEC EDGAR network queries, LangGraph state checkpoints, mathematical validation, and cryptographic ledgers.
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {pillars.map((p, idx) => {
            const Icon = p.icon
            return (
              <div
                key={idx}
                className="rounded-xl border border-slate-200/90 bg-slate-50/50 p-6 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                    <Icon className="h-5 w-5" />
                  </div>
                  <span className="font-mono text-[11px] font-semibold text-slate-500 bg-white px-2 py-0.5 rounded border border-slate-200">
                    {p.module}
                  </span>
                </div>

                <h3 className="mt-4 text-base font-bold text-slate-900">{p.title}</h3>
                <p className="mt-2 text-xs leading-relaxed text-slate-600">{p.description}</p>
              </div>
            )
          })}
        </div>

        {/* Live Python Bridge Callout */}
        <div className="mt-12 rounded-2xl bg-slate-900 p-8 text-white flex flex-col md:flex-row md:items-center md:justify-between gap-6 shadow-xl">
          <div>
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-semibold text-emerald-400">
                Local Python Engine Ready
              </span>
            </div>
            <h3 className="mt-2 text-xl font-bold">
              Run Complete Audits in Python Streamlit
            </h3>
            <p className="mt-1 text-xs text-slate-300 max-w-xl">
              Execute live SEC Form 10-K extraction, 5-factor confidence scoring, and accounting identity validation directly within the integrated workspace.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="/app/audits/new"
              className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-xs font-semibold text-white shadow-md hover:bg-blue-500 whitespace-nowrap cursor-pointer"
            >
              <Terminal className="h-4 w-4" />
              <span>Initiate Audit Run</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
      </div>
    </section>
  )
}
