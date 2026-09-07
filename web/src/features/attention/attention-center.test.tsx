// The bell as the CEO sees it: badge counts errors+warnings only, the panel lists rows
// most-severe first with deep links, dismissals persist (and un-hide when the item
// changes), and the panel closes on outside pointer / Escape.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
import { AttentionCenter } from './attention-center'

// jsdom here exposes no localStorage; the repo's other storage-backed tests stub it the same way.
function installLocalStorage(): void {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size
    },
  })
}

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="loc">{loc.pathname + loc.search}</span>
}

function renderBell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/chat']}>
        <AppProviders>
          <AttentionCenter />
          <Routes>
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </AppProviders>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function mockQuiet() {
  vi.spyOn(api, 'getPendingApprovals').mockResolvedValue({ pending: [], count: 0 })
  vi.spyOn(api, 'getClarifyPending').mockResolvedValue({ questions: [] })
  vi.spyOn(api, 'getTeamTaskBoard').mockResolvedValue({ lanes: [] })
  vi.spyOn(api, 'getFleetBudget').mockResolvedValue({ agents: [], total_spent_usd: 0, total_cap_usd: 0, ratio: 0 })
  vi.spyOn(api, 'getCoordinatorHealth').mockResolvedValue({ alive: true, last_beat_ago_s: 1, reason: '', hint: '' })
  vi.spyOn(api, 'getTeamAlerts').mockResolvedValue({ alerts: [] })
  vi.spyOn(api, 'getTemplateStatus').mockResolvedValue({ agents: [] })
}

beforeEach(() => {
  vi.restoreAllMocks()
  installLocalStorage()
  mockQuiet()
})

test('quiet fleet: no badge, panel says nothing needs attention', async () => {
  renderBell()
  fireEvent.click(screen.getByRole('button', { name: 'Cần chú ý (0)' }))
  expect(await screen.findByText('Không có gì cần chú ý.')).toBeTruthy()
  expect(screen.queryByTestId('attention-badge')).toBeNull()
})

test('badge = errors + warnings (info excluded); rows most-severe first; link navigates and closes', async () => {
  vi.spyOn(api, 'getPendingApprovals').mockResolvedValue({
    pending: [{ agent_id: 'content', id: 7, reason: 'Đăng bài', status: 'pending',
      created_at: '2026-09-07T01:00:00Z', action: { type: 'mcp_tool' } }],
    count: 1,
  })
  vi.spyOn(api, 'getCoordinatorHealth').mockResolvedValue({
    alive: false, last_beat_ago_s: null, reason: 'no_heartbeat', hint: 'Chạy my-crew serve',
  })
  vi.spyOn(api, 'getTemplateStatus').mockResolvedValue({
    agents: [{ agent_id: 'hr', role: 'hr', applied_version: 1, latest_version: 2, upgradable: true }],
  })
  renderBell()
  expect(await screen.findByTestId('attention-badge')).toHaveTextContent('2')

  fireEvent.click(screen.getByRole('button', { name: 'Cần chú ý (2)' }))
  const panel = screen.getByTestId('attention-panel')
  const rows = within(panel).getAllByRole('listitem')
  expect(rows.map((r) => r.getAttribute('data-severity'))).toEqual(['error', 'warning', 'info'])
  expect(within(rows[0]).getByText('Điều phối viên không chạy')).toBeTruthy()
  expect(within(rows[1]).getByText('content chờ duyệt')).toBeTruthy()
  expect(within(rows[2]).getByText('v1 → v2')).toBeTruthy()

  fireEvent.click(within(rows[0]).getByRole('link'))
  expect(screen.getByTestId('loc')).toHaveTextContent('/system?tab=settings')
  expect(screen.queryByTestId('attention-panel')).toBeNull()
})

test('dismiss hides one row and persists; mark-all clears the badge; changed item returns', async () => {
  const alerts = vi.spyOn(api, 'getTeamAlerts').mockResolvedValue({
    alerts: [
      { kind: 'failing', agent_id: 'hr', message: 'lỗi 3 lần', severity: 'high' },
      { kind: 'deny_spike', agent_id: 'content', message: 'từ chối 4 lần', severity: 'warn' },
    ],
  })
  const { unmount } = renderBell()
  expect(await screen.findByTestId('attention-badge')).toHaveTextContent('2')
  fireEvent.click(screen.getByRole('button', { name: 'Cần chú ý (2)' }))
  const panel = screen.getByTestId('attention-panel')
  fireEvent.click(within(within(panel).getAllByRole('listitem')[0]).getByRole('button', { name: 'Bỏ qua' }))
  expect(within(panel).getAllByRole('listitem')).toHaveLength(1)
  expect(within(panel).getByText('1 mục đã bỏ qua')).toBeTruthy()
  expect(screen.getByTestId('attention-badge')).toHaveTextContent('1')

  fireEvent.click(within(panel).getByRole('button', { name: 'Đã xem tất cả' }))
  expect(screen.queryByTestId('attention-badge')).toBeNull()
  expect(within(panel).getByText('Không có gì cần chú ý.')).toBeTruthy()
  unmount()

  // A remount reads the persisted dismissals — but the hr alert's message changed, so
  // that one is a new fingerprint and surfaces again while content stays hidden.
  alerts.mockResolvedValue({
    alerts: [
      { kind: 'failing', agent_id: 'hr', message: 'lỗi 5 lần', severity: 'high' },
      { kind: 'deny_spike', agent_id: 'content', message: 'từ chối 4 lần', severity: 'warn' },
    ],
  })
  renderBell()
  expect(await screen.findByTestId('attention-badge')).toHaveTextContent('1')
  fireEvent.click(screen.getByRole('button', { name: 'Cần chú ý (1)' }))
  expect(screen.getByText('lỗi 5 lần')).toBeTruthy()
  expect(screen.queryByText('từ chối 4 lần')).toBeNull()
})

test('outside pointerdown and Escape close the panel', async () => {
  renderBell()
  const bell = screen.getByRole('button', { name: 'Cần chú ý (0)' })
  fireEvent.click(bell)
  expect(screen.getByTestId('attention-panel')).toBeTruthy()
  fireEvent.pointerDown(document.body)
  await waitFor(() => expect(screen.queryByTestId('attention-panel')).toBeNull())
  fireEvent.click(bell)
  expect(bell.getAttribute('aria-expanded')).toBe('true')
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByTestId('attention-panel')).toBeNull())
})
