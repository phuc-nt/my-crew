// Router root. browser-router at `/` — the SPA is served at the root by FastAPI's
// StaticFiles(html=True) mount (S5); client routes deep-link via the index.html catch-all.
// v6 M16: on load, /api/me decides login vs dashboard; a 401 anywhere flips back to login.
import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import './App.css'
import { AgentProvider } from './agent-context'
import { api, setUnauthorizedHandler } from './api/client'
import { useLanguage } from './i18n/language-context'
import { AdvancedAgentView } from './components/AdvancedAgentView'
import { Layout } from './components/Layout'
import { PendingApprovalsProvider } from './pending-approvals-context'
import { AgentPage } from './views/AgentPage'
import { Chat } from './views/Chat'
import { Captures } from './views/Captures'
import { CompanyActivity } from './views/CompanyActivity'
import { CompanyDocs } from './views/CompanyDocs'
import { Config } from './views/Config'
import { Connections } from './views/Connections'
import { Cost } from './views/Cost'
import { CreateAgent } from './views/CreateAgent'
import { Guardrail } from './views/Guardrail'
import { Login } from './views/Login'
import { MemoryAutomation } from './views/MemoryAuto'
import { OfficeRoom } from './views/OfficeRoom'
import { OfficeUnifiedLazy } from './routes/office-unified-lazy'
import { Outputs } from './views/Outputs'
import { Overview } from './views/Overview'
import { Settings } from './views/Settings'
import { Setup } from './views/Setup'
import { Team } from './views/Team'
import { Timeline } from './views/Timeline'
import { Trigger } from './views/Trigger'
import { Work } from './views/Work'

function App() {
  const { t } = useLanguage()
  // null = still checking; true/false = authenticated or not.
  const [authed, setAuthed] = useState<boolean | null>(null)
  // v7 M17: first-run setup. null = unknown; false = needs wizard; true = done.
  const [setupDone, setSetupDone] = useState<boolean | null>(null)

  const check = useCallback(() => {
    // Check setup first: an un-setup server has no auth, so the wizard must precede login.
    api
      .setupStatus()
      .then((s) => {
        setSetupDone(s.completed)
        if (s.completed) {
          api
            .getMe()
            .then((m) => setAuthed(m.authenticated))
            .catch(() => setAuthed(false))
        }
      })
      .catch(() => {
        // status should never 401 (public); on any error assume done + fall to auth check
        setSetupDone(true)
        api
          .getMe()
          .then((m) => setAuthed(m.authenticated))
          .catch(() => setAuthed(false))
      })
  }, [])

  useEffect(() => {
    check()
    setUnauthorizedHandler(() => setAuthed(false)) // any 401 → back to login
  }, [check])

  if (setupDone === null) return <p style={{ padding: '2rem' }}>{t('app.loading')}</p>
  if (!setupDone) return <Setup onDone={check} />
  if (authed === null) return <p style={{ padding: '2rem' }}>{t('app.loading')}</p>
  if (!authed) return <Login onLoggedIn={check} />

  return (
    <BrowserRouter>
      <AgentProvider>
        <Routes>
          <Route
            path="/"
            element={
              <PendingApprovalsProvider>
                <Layout />
              </PendingApprovalsProvider>
            }
          >
            {/* v7 M20: 4 CEO-first destinations. Default is the assistant (chat). */}
            {/* v17: the office IS the product's home screen. */}
            <Route index element={<Navigate to="/office" replace />} />
            <Route path="chat" element={<Chat />} />
            <Route path="team" element={<Team />} />
            <Route path="work" element={<Work />} />
            <Route path="settings" element={<Settings />} />
            {/* v33 P1: Connections — the UI version of .env (fixed catalog). */}
            <Route path="connections" element={<Connections />} />
            {/* v33 P3: outputs hub — every delivered artifact/file, one list. */}
            <Route path="outputs" element={<Outputs />} />
            {/* Agent page + non-agent advanced views. */}
            <Route path="agents/:id" element={<AgentPage />} />
            <Route path="create" element={<CreateAgent />} />
            <Route path="company-docs" element={<CompanyDocs />} />
            {/* v31 P1: fleet-wide post-hoc audit — CEO-primary in autonomy-first. */}
            <Route path="company-activity" element={<CompanyActivity />} />
            {/* Dual-lens P3: per-attempt telemetry explorer (ADVANCED_NAV). */}
            <Route path="captures" element={<Captures />} />
            {/* v15: the unified office — 3D + live feed + composer, one SSE stream.
                Lazy so three/@react-three/fiber never land in the main bundle. */}
            <Route path="office" element={<OfficeUnifiedLazy />} />
            {/* The full timeline (room picker + complete history) stays as its own tab. */}
            <Route path="office/timeline" element={<OfficeRoom />} />
            {/* Pre-v15 bookmark compatibility: the 3D view merged into /office. */}
            <Route path="office/3d" element={<Navigate to="/office" replace />} />
            {/* Per-agent technical views (Nâng cao) — wrapped with the agent picker they
                need, since the global picker was removed from the top nav (M20). */}
            <Route element={<AdvancedAgentView />}>
              <Route path="overview" element={<Overview />} />
              <Route path="timeline" element={<Timeline />} />
              <Route path="cost" element={<Cost />} />
              <Route path="memory" element={<MemoryAutomation />} />
              <Route path="guardrail" element={<Guardrail />} />
              <Route path="config" element={<Config />} />
              <Route path="trigger" element={<Trigger />} />
            </Route>
            {/* Old URLs → new homes so bookmarks/links survive the M20 reorg. */}
            <Route path="approvals" element={<Navigate to="/work" replace />} />
            <Route path="tasks" element={<Navigate to="/work" replace />} />
          </Route>
        </Routes>
      </AgentProvider>
    </BrowserRouter>
  )
}

export default App
