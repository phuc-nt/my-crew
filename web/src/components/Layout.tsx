// App shell (v7 M20): CEO-first nav — 4 primary destinations (Trợ lý / Đội / Việc / Cài đặt)
// instead of the old flat 12-item bar. "Việc" carries a badge with the total pending-approval
// count across all agents (client-side aggregate — no new backend). The old per-agent global
// picker is gone: per-agent context now lives on each agent page (M18). Technical views
// (Overview/Timeline/Guardrail/Trigger/Memory/Cost) are reachable under Cài đặt → Nâng cao.
import { NavLink, Outlet } from 'react-router'
import { api } from '../api/client'
import { useSharedPendingApprovals } from '../pending-approvals-context'

async function logout() {
  try {
    await api.logout()
  } finally {
    window.location.reload() // simplest: reload → App re-checks /api/me → login screen
  }
}

const NAV = [
  { to: 'chat', label: 'Trợ lý' },
  { to: 'team', label: 'Đội' },
  { to: 'work', label: 'Việc', badge: true },
  { to: 'settings', label: 'Cài đặt' },
]

export function Layout() {
  const { count } = useSharedPendingApprovals()
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>my-project-manager</h1>
        <button type="button" className="logout-btn" onClick={() => void logout()}>
          Đăng xuất
        </button>
      </header>
      <nav className="app-nav app-nav-primary">
        {NAV.map((n) => (
          <NavLink key={n.label} to={n.to}>
            {n.label}
            {n.badge && count > 0 && <span className="nav-badge">{count}</span>}
          </NavLink>
        ))}
      </nav>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
