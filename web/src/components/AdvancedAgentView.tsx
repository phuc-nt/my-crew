// v7 M20: wrapper for the advanced per-agent technical views (Overview/Config/Trigger).
// The global agent picker was removed from the top nav, but these views still query one
// selected agent — so the picker rides here, only on the pages that actually need it.
import { Link, Outlet } from 'react-router'
import { AgentPicker } from './AgentPicker'

export function AdvancedAgentView() {
  return (
    <div className="advanced-agent-view">
      <div className="advanced-bar">
        <Link to="/settings" className="muted">
          ← Cài đặt
        </Link>
        <AgentPicker />
      </div>
      <Outlet />
    </div>
  )
}
