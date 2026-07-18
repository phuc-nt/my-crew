// App shell (v7 M20): CEO-first nav — primary destinations (Trợ lý / Đội / Việc / Văn phòng /
// Cài đặt) instead of the old flat 12-item bar. "Việc" carries a badge with the total
// pending-approval count across all agents (client-side aggregate — no new backend). The old
// per-agent global picker is gone: per-agent context now lives on each agent page (M18).
// Technical views (Overview/Timeline/Guardrail/Trigger/Memory/Cost) are reachable under
// Cài đặt → Nâng cao. "Văn phòng" (v12 M29) is the team's live activity timeline; "Văn phòng 3D"
// (v12 M30) is a lazy-loaded 3D wireframe view of the same event stream, linked as a secondary
// item next to it rather than its own top-level nav slot (keeps the primary row at 4 CEO items).
import { NavLink, Outlet } from 'react-router'
import { api } from '../api/client'
import { useTeamHealth } from '../hooks/use-team-health'
import { useSharedPendingApprovals } from '../pending-approvals-context'
import { useUiMode } from '../ui-mode-context'
import { ThemeToggle } from './ThemeToggle'

async function logout() {
  try {
    await api.logout()
  } finally {
    window.location.reload() // simplest: reload → App re-checks /api/me → login screen
  }
}

// v17 IA: Văn phòng leads (the home screen); "Việc" became "Duyệt" — that tab is the
// approval queue (+ the per-agent assigned board below it); team-task history lives in
// the office's workrooms.
const NAV = [
  { to: 'office', label: 'Văn phòng' },
  { to: 'team', label: 'Đội', badge: 'health' as const },
  { to: 'work', label: 'Duyệt', badge: 'approvals' as const },
  // v33 P3: the cross-room outputs hub — "mọi kết quả một chỗ" sits one click away.
  { to: 'outputs', label: 'Kết quả' },
  // v31 P1: fleet-wide "what did the company do" — the post-hoc audit surface of
  // autonomy-first, so it sits in the CEO-primary row (NOT behind high ui-mode).
  { to: 'company-activity', label: 'Hoạt động' },
  { to: 'chat', label: 'Trợ lý' },
  { to: 'settings', label: 'Cài đặt' },
]

// High-mode ("Chế độ nâng cao") extra destinations — the technical views that low mode keeps
// tucked under Cài đặt → Nâng cao. Same routes, just surfaced in the nav for power users.
const ADVANCED_NAV = [
  { to: 'overview', label: 'Tổng quan' },
  { to: 'timeline', label: 'Dòng thời gian' },
  { to: 'cost', label: 'Chi phí' },
  { to: 'memory', label: 'Bộ nhớ' },
  { to: 'guardrail', label: 'Guardrail' },
  { to: 'config', label: 'Cấu hình' },
  { to: 'trigger', label: 'Chạy tay' },
  // v15: the 3D view merged into the primary "Văn phòng" screen; this advanced entry is
  // the full room-by-room timeline (complete history + room picker).
  { to: 'office/timeline', label: 'Nhật ký văn phòng' },
]

export function Layout() {
  const { count } = useSharedPendingApprovals()
  const { highCount } = useTeamHealth()
  const { isHigh, setMode } = useUiMode()
  const badgeFor = (b?: 'health' | 'approvals') =>
    b === 'approvals' ? count : b === 'health' ? highCount : 0
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>my-crew</h1>
        <div className="app-header-actions">
          {/* Dual-lens P2: the low/high lens toggle moves up here from Settings (which
              keeps its control as a mirror — same context). View-layer only, never a
              permission (ui-mode-context.tsx). */}
          <button
            type="button"
            className="chip mode-toggle"
            onClick={() => setMode(isHigh ? 'low' : 'high')}
            title={isHigh ? 'Đang: chế độ kỹ thuật — bấm về chế độ thường' : 'Đang: chế độ thường — bấm sang chế độ kỹ thuật'}
          >
            {isHigh ? '🔬 Kỹ thuật' : '👁 Thường'}
          </button>
          <ThemeToggle />
          <button type="button" className="logout-btn" onClick={() => void logout()}>
            Đăng xuất
          </button>
        </div>
      </header>
      <nav className="app-nav app-nav-primary">
        {NAV.map((n) => {
          const badgeCount = badgeFor(n.badge)
          return (
            <NavLink key={n.label} to={n.to}>
              {n.label}
              {badgeCount > 0 && <span className="nav-badge">{badgeCount}</span>}
            </NavLink>
          )
        })}
      </nav>
      {isHigh && (
        <nav className="app-nav app-nav-advanced" aria-label="Nâng cao">
          {ADVANCED_NAV.map((n) => (
            <NavLink key={n.to} to={n.to}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      )}
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
