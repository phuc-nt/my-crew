// v7 M20 Work page: aggregates pending approvals across agents + approve/reject; embeds the
// tasks board. Mocked api, no network. Wrapped in a router (uses <Link>).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { Work } from './Work'

const APPROVAL = {
  id: 7,
  reason: 'gửi báo cáo ra kênh stakeholder',
  status: 'pending',
  created_at: 't1',
  action: { kind: 'slack_post', channel: 'ext' },
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'hr', name: 'HR', enabled: true, last_run: null },
    { id: 'pm', name: 'PM', enabled: true, last_run: null },
  ] as never)
  vi.spyOn(api, 'getApprovals').mockImplementation(async (id: string) =>
    id === 'hr'
      ? { agent_id: 'hr', pending: [APPROVAL] }
      : { agent_id: 'pm', pending: [] },
  )
  vi.spyOn(api, 'getTasks').mockResolvedValue({ agents: [] } as never)
})

function renderWork() {
  return render(
    <MemoryRouter>
      <Work />
    </MemoryRouter>,
  )
}

test('lists pending approvals across agents with the agent id', async () => {
  renderWork()
  expect(await screen.findByText(/gửi báo cáo ra kênh stakeholder/)).toBeInTheDocument()
  expect(screen.getByText('hr')).toBeInTheDocument()
})

test('approve calls the agent-scoped approve endpoint after confirm', async () => {
  const approve = vi.spyOn(api, 'approve').mockResolvedValue({ agent_id: 'hr', pending: [] })
  renderWork()
  fireEvent.click(await screen.findByText('Xem & duyệt'))
  fireEvent.click(await screen.findByText('Approve & post'))
  await waitFor(() => expect(approve).toHaveBeenCalledWith('hr', 7))
})

test('reject calls the agent-scoped reject endpoint', async () => {
  const reject = vi.spyOn(api, 'reject').mockResolvedValue({ agent_id: 'hr', pending: [] })
  renderWork()
  fireEvent.click(await screen.findByText('Từ chối'))
  await waitFor(() => expect(reject).toHaveBeenCalledWith('hr', 7))
})

test('shows empty state when nothing is pending', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'x', pending: [] })
  renderWork()
  expect(await screen.findByText(/Không có việc nào chờ duyệt/)).toBeInTheDocument()
})
