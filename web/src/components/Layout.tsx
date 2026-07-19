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
import { useLanguage } from '../i18n/language-context'
import type { UiKey } from '../i18n/dictionary'
import { useSharedPendingApprovals } from '../pending-approvals-context'
import { useUiMode } from '../ui-mode-context'
import { SearchBox } from './search-box'
import { ThemeToggle } from './ThemeToggle'
import { Button } from './ui/button'

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
// v53: labels live in the i18n dictionary (labelKey), rendered via t() so the VN/EN
// toggle re-labels the whole nav.
const NAV: { to: string; labelKey: UiKey; badge?: 'health' | 'approvals' }[] = [
  { to: 'office', labelKey: 'nav.office' },
  { to: 'team', labelKey: 'nav.team', badge: 'health' },
  { to: 'work', labelKey: 'nav.work', badge: 'approvals' },
  // v33 P3: the cross-room outputs hub — "mọi kết quả một chỗ" sits one click away.
  { to: 'outputs', labelKey: 'nav.outputs' },
  // v31 P1: fleet-wide "what did the company do" — the post-hoc audit surface of
  // autonomy-first, so it sits in the CEO-primary row (NOT behind high ui-mode).
  { to: 'company-activity', labelKey: 'nav.activity' },
  { to: 'chat', labelKey: 'nav.chat' },
  { to: 'settings', labelKey: 'nav.settings' },
]

// High-mode ("Chế độ nâng cao") extra destinations — the technical views that low mode keeps
// tucked under Cài đặt → Nâng cao. Same routes, just surfaced in the nav for power users.
const ADVANCED_NAV: { to: string; labelKey: UiKey }[] = [
  { to: 'overview', labelKey: 'nav.advanced.overview' },
  { to: 'timeline', labelKey: 'nav.advanced.timeline' },
  { to: 'cost', labelKey: 'nav.advanced.cost' },
  { to: 'memory', labelKey: 'nav.advanced.memory' },
  { to: 'guardrail', labelKey: 'nav.advanced.guardrail' },
  { to: 'config', labelKey: 'nav.advanced.config' },
  { to: 'trigger', labelKey: 'nav.advanced.trigger' },
  // Dual-lens P3: per-attempt telemetry explorer over the v26 captures store.
  { to: 'captures', labelKey: 'nav.advanced.captures' },
  // v15: the 3D view merged into the primary "Văn phòng" screen; this advanced entry is
  // the full room-by-room timeline (complete history + room picker).
  { to: 'office/timeline', labelKey: 'nav.advanced.officeLog' },
]

export function Layout() {
  const { count } = useSharedPendingApprovals()
  const { highCount } = useTeamHealth()
  const { isHigh, setMode } = useUiMode()
  const { lang, setLang, t } = useLanguage()
  const badgeFor = (b?: 'health' | 'approvals') =>
    b === 'approvals' ? count : b === 'health' ? highCount : 0
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>my-crew</h1>
        <div className="app-header-actions">
          {/* Dual-lens P3: FTS5 history search — a maintainer tool, high mode only. */}
          {isHigh && <SearchBox />}
          {/* Dual-lens P2: the low/high lens toggle moves up here from Settings (which
              keeps its control as a mirror — same context). View-layer only, never a
              permission (ui-mode-context.tsx). */}
          <Button
            variant="chip"
            className="mode-toggle"
            onClick={() => setMode(isHigh ? 'low' : 'high')}
            title={isHigh ? t('chrome.modeHighTitle') : t('chrome.modeLowTitle')}
          >
            {isHigh ? t('chrome.modeHigh') : t('chrome.modeLow')}
          </Button>
          {/* v53 language mode — VN/EN for FE-static strings (view-layer; backend/LLM
              content stays as-is by design). */}
          <Button variant="chip" onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}>
            {lang === 'vi' ? 'VN' : 'EN'}
          </Button>
          <ThemeToggle />
          {/* v53: .logout-btn styled standalone (not .btn family) — Button's ghost variant
              would add .btn on top and change the visual; keep raw this pass. */}
          <button type="button" className="logout-btn" onClick={() => void logout()}>
            {t('chrome.logout')}
          </button>
        </div>
      </header>
      <nav className="app-nav app-nav-primary">
        {NAV.map((n) => {
          const badgeCount = badgeFor(n.badge)
          return (
            <NavLink key={n.to} to={n.to}>
              {t(n.labelKey)}
              {badgeCount > 0 && <span className="nav-badge">{badgeCount}</span>}
            </NavLink>
          )
        })}
      </nav>
      {isHigh && (
        <nav className="app-nav app-nav-advanced" aria-label={t('nav.advancedLabel')}>
          {ADVANCED_NAV.map((n) => (
            <NavLink key={n.to} to={n.to}>
              {t(n.labelKey)}
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
