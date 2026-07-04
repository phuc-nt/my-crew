// v7 M20 Layout: 4 primary nav items + a pending-approval badge on "Việc". Mocked api.
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { PendingApprovalsProvider } from '../pending-approvals-context'
import { Layout } from './Layout'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'hr', name: 'HR', enabled: true, last_run: null },
  ] as never)
})

function renderLayout() {
  return render(
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
    </MemoryRouter>,
  )
}

test('renders the 4 CEO-first nav items', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'hr', pending: [] })
  renderLayout()
  for (const label of ['Trợ lý', 'Đội', 'Việc', 'Cài đặt']) {
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
    expect(screen.getByRole('link', { name: /Việc/ })).toHaveTextContent('1'),
  )
})
