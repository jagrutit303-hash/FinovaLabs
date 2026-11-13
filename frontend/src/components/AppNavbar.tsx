import React, { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  PlusCircle,
  ClipboardList,
  BarChart3,
  LineChart,
  Settings,
  Home,
  Menu,
  X,
  ExternalLink,
} from 'lucide-react'
import { api } from '../api/client'
import type { HealthResponse } from '../api/client'

export const AppNavbar: React.FC = () => {
  const location = useLocation()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    api.getHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [location.pathname])

  const navItems = [
    { label: 'Overview', path: '/app', icon: Home },
    { label: 'New Audit', path: '/app/audits/new', icon: PlusCircle },
    { label: 'Analytics', path: '/app/analytics', icon: LineChart },
    { label: 'Review Center', path: '/app/reviews', icon: ClipboardList },
    { label: 'Reports & History', path: '/app/reports', icon: BarChart3 },
    { label: 'Settings', path: '/app/settings', icon: Settings },
  ]

  const isActive = (path: string) => {
    if (path === '/app') {
      return location.pathname === '/app'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-200 bg-white/95 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2.5 group">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm ring-1 ring-slate-800 transition-transform group-hover:scale-105">
              <svg
                className="h-5 w-5"
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
                <span className="font-serif text-lg font-bold tracking-tight text-slate-950">
                  Finova<span className="text-blue-600">Labs</span>
                </span>
                <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 ring-1 ring-blue-600/20">
                  v1.0
                </span>
              </div>
              <p className="text-[10px] font-medium text-slate-500 hidden sm:block">
                Financial Filing Auditor
              </p>
            </div>
          </Link>

          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1 pl-4 border-l border-slate-200">
            {navItems.map((item) => {
              const Icon = item.icon
              const active = isActive(item.path)
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`inline-flex items-center gap-2 px-3 py-2 text-xs font-semibold rounded-lg transition-colors ${
                    active
                      ? 'bg-blue-50 text-blue-700 ring-1 ring-blue-600/20'
                      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                  }`}
                >
                  <Icon className={`h-4 w-4 ${active ? 'text-blue-600' : 'text-slate-400'}`} />
                  <span>{item.label}</span>
                </Link>
              )
            })}
          </nav>
        </div>

        {/* Right Action: Status & Landing link */}
        <div className="flex items-center gap-3">
          {/* Health indicator */}
          <div className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded-full bg-slate-50 border border-slate-200 text-xs">
            {health?.healthy ? (
              <>
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-slate-600 font-medium">SQLite WAL Active</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 rounded-full bg-amber-500" />
                <span className="text-slate-500 font-medium">Connecting...</span>
              </>
            )}
          </div>

          <Link
            to="/"
            className="hidden sm:inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900 px-2.5 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50"
          >
            <span>Landing</span>
            <ExternalLink className="h-3 w-3 text-slate-400" />
          </Link>

          {/* Mobile menu toggle */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden p-2 text-slate-600 hover:bg-slate-100 rounded-lg"
            aria-label="Toggle Navigation"
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Nav dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-slate-200 bg-white px-4 pt-2 pb-4 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = isActive(item.path)
            return (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setMobileMenuOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium ${
                  active
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-700 hover:bg-slate-100'
                }`}
              >
                <Icon className={`h-4 w-4 ${active ? 'text-blue-600' : 'text-slate-400'}`} />
                <span>{item.label}</span>
              </Link>
            )
          })}
          <div className="pt-2 border-t border-slate-100">
            <Link
              to="/"
              onClick={() => setMobileMenuOpen(false)}
              className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-slate-600"
            >
              <span>Back to Public Landing Page</span>
            </Link>
          </div>
        </div>
      )}
    </header>
  )
}
