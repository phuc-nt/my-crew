// v7 M20 Layout (v17 IA: 'Việc' renamed 'Duyệt', Văn phòng leads). Mocked api.
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { PendingApprovalsProvider } from '../pending-approvals-context'
import { AppProviders } from '../test-utils'
import { Layout } from './Layout'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'hr', name: 'HR', enabled: true, last_run: null },
  ] as never)
})

function renderLayout() {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route
            path="/"
            element={
              <PendingApprovalsProvider>
                <Layout />
              </PendingApprovalsProvider>
            }
          >
            <Route path="chat" element={<div>chat body</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AppProviders>,
  )
}

test('renders the CEO-first nav items', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'hr', pending: [] })
  renderLayout()
  for (const label of ['Trợ lý', 'Đội', 'Duyệt', 'Hoạt động', 'Văn phòng', 'Cài đặt']) {
    expect(screen.getByRole('link', { name: new RegExp(label) })).toBeInTheDocument()
  }
})

test('shows a badge count when approvals are pending', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({
    agent_id: 'hr',
    pending: [{ id: 1, reason: 'r', status: 'pending', created_at: 't', action: {} }],
  })
  renderLayout()
  await waitFor(() =>
    expect(screen.getByRole('link', { name: /Duyệt/ })).toHaveTextContent('1'),
  )
})

test('shows a health badge on Đội when a high-severity alert exists (M21)', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'hr', pending: [] })
  vi.spyOn(api, 'getTeamAlerts').mockResolvedValue({
    alerts: [
      { kind: 'missed_schedule', agent_id: 'hr', message: 'quá hạn', severity: 'high' },
      { kind: 'budget', agent_id: 'pm', message: 'b', severity: 'warn' }, // warn not counted
    ],
  })
  renderLayout()
  await waitFor(() => expect(screen.getByRole('link', { name: /Đội/ })).toHaveTextContent('1'))
})
