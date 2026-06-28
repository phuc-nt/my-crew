// App shell: top nav linking the 5 view groups + the agent picker. The selected agent id
// lives in the shared agent context (useAgent); Layout renders nav + the routed <Outlet/>.
import { NavLink, Outlet } from 'react-router'
import { AgentPicker } from './AgentPicker'

const NAV = [
  { to: '', label: 'Overview' },
  { to: 'timeline', label: 'Timeline' },
  { to: 'cost', label: 'Cost' },
  { to: 'memory', label: 'Memory & Automation' },
  { to: 'guardrail', label: 'Guardrail' },
]

export function Layout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>my-project-manager · agent dashboard</h1>
        <AgentPicker />
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
