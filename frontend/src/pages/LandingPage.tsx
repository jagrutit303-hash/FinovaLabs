import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Hero66 } from '../components/Hero66'
import { BackendPillars } from '../components/BackendPillars'
import { Footer } from '../components/Footer'
import { Navbar } from '../components/Navbar'

export const LandingPage: React.FC = () => {
  const navigate = useNavigate()

  const handleStartAudit = () => {
    navigate('/app/audits/new')
  }

  const handleExploreHowItWorks = () => {
    const el = document.getElementById('how-it-works')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 font-sans selection:bg-blue-600 selection:text-white">
      <Navbar
        onStartAudit={handleStartAudit}
        onExploreHowItWorks={handleExploreHowItWorks}
        activeView="landing"
        setActiveView={(v) => {
          if (v === 'workspace') navigate('/app')
        }}
      />
      <main>
        <Hero66
          onStartAudit={handleStartAudit}
          onExploreHowItWorks={handleExploreHowItWorks}
        />
        <BackendPillars />
      </main>
      <Footer />
    </div>
  )
}

