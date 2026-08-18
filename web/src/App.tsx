// Router root. browser-router at `/` — the SPA is served at the root by FastAPI's
// StaticFiles(html=True) mount (S5); client routes deep-link via the index.html catch-all.
// v6 M16: on load, /api/me decides login vs dashboard; a 401 anywhere flips back to login.
//
// This file is deliberately only the pre-router gate. The shell, providers, and route
// table live under `app/` so a hub can be swapped without touching the auth flow.
import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter } from 'react-router'
import './App.css'
import { api, setUnauthorizedHandler } from './api/client'
import { AppProviders } from './app/app-providers'
import { AppRoutes } from './app/app-routes'
import { useLanguage } from './i18n/language-context'
import { Login } from './views/Login'
import { Setup } from './views/Setup'

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
      <AppProviders>
        <AppRoutes />
      </AppProviders>
    </BrowserRouter>
  )
}

export default App
