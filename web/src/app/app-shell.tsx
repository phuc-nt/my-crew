// The 5-hub shell: Trò chuyện · Văn phòng · Công việc · Đội ngũ · Hệ thống.
//
// Replaces the 7-primary + 9-advanced nav. The advanced row is gone as a *navigation*
// concept — those views become tabs inside the hub that owns them — but the ui-mode
// toggle stays, because individual hubs still hide technical panels behind it.
//
// The approvals badge reads the fleet index (one request) instead of fanning out per
// agent, so adding a second surface that shows the queue costs nothing.
import { NavLink, Outlet, useLocation } from 'react-router'
import { RouteErrorBoundary } from './app-error-boundary'
import { UpdateAvailableBanner } from './update-available-banner'
import { api } from '../api/client'
import { ChromeOverflowMenu } from './chrome-overflow-menu'
import { usePendingApprovals } from '../api/queries/use-approvals-queries'
import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/ui/button'
import { AttentionCenter } from '../features/attention/attention-center'
import { AppWalkthrough } from '../features/onboarding/app-walkthrough'
import { CommandPalette } from '../features/palette/command-palette'
import { SHORTCUTS_OPEN_EVENT, ShortcutsHelp } from '../features/palette/shortcuts-help'
import type { UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import { useUiMode } from '../ui-mode-context'

async function logout() {
  try {
    await api.logout()
  } finally {
    window.location.reload() // reload → App re-checks /api/me → login screen
  }
}

const HUBS: { to: string; labelKey: UiKey; badge?: 'approvals' }[] = [
  { to: '/chat', labelKey: 'hub.chat' },
  { to: '/office', labelKey: 'hub.office' },
  { to: '/work', labelKey: 'hub.work', badge: 'approvals' },
  { to: '/team', labelKey: 'hub.team' },
  { to: '/system', labelKey: 'hub.system' },
]

export function AppShell() {
  const { data: approvals } = usePendingApprovals()
  const { isHigh, setMode } = useUiMode()
  const { lang, setLang, t } = useLanguage()
  const approvalCount = approvals?.count ?? 0
  const { pathname } = useLocation()

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>my-crew</h1>
        {/* Same four controls, two presentations: inline on desktop, collapsed behind ⋯
            on a phone. CSS picks one — rendering both keeps the desktop markup (and its
            tests) untouched while the mobile header stays one row. */}
        <div className="app-header-actions">
          <Button
            variant="chip"
            className="mode-toggle"
            onClick={() => setMode(isHigh ? 'low' : 'high')}
            title={isHigh ? t('chrome.modeHighTitle') : t('chrome.modeLowTitle')}
          >
            {isHigh ? t('chrome.modeHigh') : t('chrome.modeLow')}
          </Button>
          <Button variant="chip" onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}>
            {lang === 'vi' ? 'VN' : 'EN'}
          </Button>
          <ThemeToggle />
          <Button
            variant="chip"
            title={t('shortcuts.button')}
            aria-label={t('shortcuts.button')}
            data-walkthrough="shortcuts"
            onClick={() => window.dispatchEvent(new Event(SHORTCUTS_OPEN_EVENT))}
          >
            ⌨
          </Button>
          <button type="button" className="logout-btn" onClick={() => void logout()}>
            {t('chrome.logout')}
          </button>
        </div>
        {/* Outside the collapsible group: the bell must stay visible on a phone. */}
        <AttentionCenter />
        <ChromeOverflowMenu onLogout={() => void logout()} />
      </header>
      <nav className="app-nav app-nav-primary" data-walkthrough="hubs">
        {HUBS.map((hub) => (
          <NavLink key={hub.to} to={hub.to}>
            {t(hub.labelKey)}
            {hub.badge === 'approvals' && approvalCount > 0 && (
              <span className="nav-badge">{approvalCount}</span>
            )}
          </NavLink>
        ))}
      </nav>
      <UpdateAvailableBanner />
      <main className="app-main">
        {/* Keyed by pathname: a crash in one hub is left behind by navigating away. */}
        <RouteErrorBoundary key={pathname}>
          <Outlet />
        </RouteErrorBoundary>
      </main>
      {/* Shell-level, not per-hub: Cmd+K has to reach the same three sources from
          wherever the CEO happens to be. Renders null until opened. */}
      <CommandPalette />
      <ShortcutsHelp />
      {/* v96: first-visit tour; renders null once seen. */}
      <AppWalkthrough />
    </div>
  )
}
