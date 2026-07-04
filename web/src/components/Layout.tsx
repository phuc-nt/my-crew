// App shell: top nav linking the 5 view groups + the agent picker. The selected agent id
// lives in the shared agent context (useAgent); Layout renders nav + the routed <Outlet/>.
import { NavLink, Outlet } from 'react-router'
import { api } from '../api/client'
import { AgentPicker } from './AgentPicker'

async function logout() {
  try {
    await api.logout()
  } finally {
    window.location.reload() // simplest: reload → App re-checks /api/me → login screen
  }
}

const NAV = [
  { to: '', label: 'Overview' },
  { to: 'chat', label: 'Trợ lý' },
  { to: 'tasks', label: 'Việc đã giao' },
  { to: 'timeline', label: 'Timeline' },
  { to: 'cost', label: 'Cost' },
  { to: 'memory', label: 'Memory & Automation' },
  { to: 'guardrail', label: 'Guardrail' },
  { to: 'approvals', label: 'Approvals' },
  { to: 'config', label: 'Config' },
  { to: 'trigger', label: 'Trigger' },
  { to: 'team', label: 'Team' },
  { to: 'company-docs', label: 'Tài liệu' },
  { to: 'create', label: 'Create' },
]

export function Layout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>my-project-manager · agent dashboard</h1>
        <AgentPicker />
        <button type="button" className="logout-btn" onClick={() => void logout()}>
          Đăng xuất
        </button>
      </header>
      <nav className="app-nav">
        {NAV.map((n) => (
          <NavLink key={n.label} to={n.to} end={n.to === ''}>
            {n.label}
          </NavLink>
        ))}
      </nav>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
