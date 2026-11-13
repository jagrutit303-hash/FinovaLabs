import React from 'react'
import { Outlet } from 'react-router-dom'
import { AppNavbar } from '../components/AppNavbar'

export const AppLayout: React.FC = () => {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans flex flex-col selection:bg-blue-600 selection:text-white">
      <AppNavbar />
      <main className="flex-1">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 bg-white py-6 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div>
            <span className="font-semibold text-slate-800">FinovaLabs</span> • MINEARENA 1.0 PS-01 Financial Filing Auditor
          </div>
          <div className="font-mono text-[11px] text-slate-400">
            FastAPI Backend • SQLite WAL • LangGraph • React TS
          </div>
        </div>
      </footer>
    </div>
  )
}

