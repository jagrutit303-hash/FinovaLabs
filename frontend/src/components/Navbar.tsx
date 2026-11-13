import React from 'react'
import { ExternalLink, Terminal, Play } from 'lucide-react'

interface NavbarProps {
  onStartAudit: () => void
  onExploreHowItWorks: () => void
  activeView: 'landing' | 'workspace'
  setActiveView: (view: 'landing' | 'workspace') => void
}

export const Navbar: React.FC<NavbarProps> = ({
  onStartAudit,
  onExploreHowItWorks,
  activeView,
  setActiveView,
}) => {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/80 bg-white/90 backdrop-blur-md transition-all">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand Logo & Wordmark */}
        <div
          className="flex cursor-pointer items-center gap-3"
          onClick={() => setActiveView('landing')}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm ring-1 ring-slate-800">
            <svg
              className="h-6 w-6"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polygon points="12 2 2 7 12 12 22 7 12 2" fill="#2563EB" stroke="#1D4ED8" />
              <polyline points="2 17 12 22 22 17" stroke="#93C5FD" />
              <polyline points="2 12 12 17 22 12" stroke="#60A5FA" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-serif text-xl font-bold tracking-tight text-slate-950">
                Finova<span className="text-blue-600">Labs</span>
              </span>
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 ring-1 ring-blue-600/20">
                v1.0 PS-01
              </span>
            </div>
            <p className="text-[11px] font-medium text-slate-500">
              AI-Powered Financial Filing Auditor
            </p>
          </div>
        </div>

        {/* Desktop Navigation Links */}
        <nav className="hidden items-center gap-8 md:flex">
          <button
            onClick={() => setActiveView('landing')}
            className={`text-sm font-medium transition-colors ${activeView === 'landing'
                ? 'text-blue-600'
                : 'text-slate-600 hover:text-slate-950'
              }`}
          >
            Overview
          </button>
          <button
            onClick={onExploreHowItWorks}
            className="text-sm font-medium text-slate-600 transition-colors hover:text-slate-950"
          >
            How It Works
          </button>
          <button
            onClick={() => setActiveView('workspace')}
            className={`text-sm font-medium transition-colors ${activeView === 'workspace'
                ? 'text-blue-600'
                : 'text-slate-600 hover:text-slate-950'
              }`}
          >
            Audit Workspace
          </button>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-sm font-medium text-slate-600 transition-colors hover:text-slate-950"
            title="FastAPI Interactive Swagger Documentation"
          >
            <Terminal className="h-4 w-4 text-slate-400" />
            FastAPI Docs
            <ExternalLink className="h-3 w-3 text-slate-400" />
          </a>
        </nav>

        {/* Action CTAs */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setActiveView('workspace')}
            className="hidden text-sm font-medium text-slate-700 hover:text-slate-900 sm:block"
          >
            Explore Dashboard
          </button>
          <button
            onClick={onStartAudit}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:bg-blue-700 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-600 focus:ring-offset-2"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            <span>Start an Audit</span>
          </button>
        </div>
      </div>
    </header>
  )
}
