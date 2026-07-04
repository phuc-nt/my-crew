// Router root. browser-router at `/` — the SPA is served at the root by FastAPI's
// StaticFiles(html=True) mount (S5); client routes deep-link via the index.html catch-all.
// v6 M16: on load, /api/me decides login vs dashboard; a 401 anywhere flips back to login.
import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import './App.css'
import { AgentProvider } from './agent-context'
import { api, setUnauthorizedHandler } from './api/client'
import { Layout } from './components/Layout'
import { AgentPage } from './views/AgentPage'
import { Approvals } from './views/Approvals'
import { Chat } from './views/Chat'
import { CompanyDocs } from './views/CompanyDocs'
import { Config } from './views/Config'
import { Cost } from './views/Cost'
import { CreateAgent } from './views/CreateAgent'
import { Guardrail } from './views/Guardrail'
import { Login } from './views/Login'
import { MemoryAutomation } from './views/MemoryAuto'
import { Overview } from './views/Overview'
import { Setup } from './views/Setup'
import { Tasks } from './views/Tasks'
import { Team } from './views/Team'
import { Timeline } from './views/Timeline'
import { Trigger } from './views/Trigger'

function App() {
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

  if (setupDone === null) return <p style={{ padding: '2rem' }}>Đang tải…</p>
  if (!setupDone) return <Setup onDone={check} />
  if (authed === null) return <p style={{ padding: '2rem' }}>Đang tải…</p>
  if (!authed) return <Login onLoggedIn={check} />

  return (
    <BrowserRouter>
      <AgentProvider>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="timeline" element={<Timeline />} />
            <Route path="cost" element={<Cost />} />
            <Route path="memory" element={<MemoryAutomation />} />
            <Route path="guardrail" element={<Guardrail />} />
            <Route path="approvals" element={<Approvals />} />
            <Route path="config" element={<Config />} />
            <Route path="trigger" element={<Trigger />} />
            <Route path="team" element={<Team />} />
            <Route path="create" element={<CreateAgent />} />
            <Route path="chat" element={<Chat />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="company-docs" element={<CompanyDocs />} />
            <Route path="agents/:id" element={<AgentPage />} />
          </Route>
        </Routes>
      </AgentProvider>
    </BrowserRouter>
  )
}

export default App
