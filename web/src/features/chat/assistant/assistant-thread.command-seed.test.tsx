// v88 P5-C: (1) clicking a command in the "Trợ lý làm được gì?" list seeds the composer
// draft with its `example` WITHOUT auto-submitting — an ops command usually needs a slot
// filled in, so it must land for editing, not fire straight to /api/ops/chat; (2) the
// quick-chip row grows a stalled-tasks chip / pending-approvals chip only when the
// already-loaded board/approvals queries actually have one — reusing the SAME hooks the
// work hub and pending pane subscribe to, no new endpoint.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../../api/client'
import { AppProviders } from '../../../test-utils'
import { AssistantThread } from './assistant-thread'

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AppProviders>
        <MemoryRouter>
          <AssistantThread title="Trợ lý" />
        </MemoryRouter>
      </AppProviders>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({ available: true })
  vi.spyOn(api, 'getOpsChatCommands').mockResolvedValue({
    commands: [
      { id: 'get_status', description: 'Xem trạng thái đội', readonly: true, example: 'trạng thái đội' },
    ],
  })
  vi.spyOn(api, 'getTeamTaskBoard').mockResolvedValue({ lanes: [] })
  vi.spyOn(api, 'getPendingApprovals').mockResolvedValue({ pending: [], count: 0 })
})

test('clicking a catalog command seeds the draft with its example and sends nothing', async () => {
  const send = vi.spyOn(api, 'opsChat')
  wrap()

  fireEvent.click(await screen.findByText(/Trợ lý làm được gì\?/))
  fireEvent.click(await screen.findByText('Xem trạng thái đội'))

  const input = screen.getByPlaceholderText('Nhắn cho trợ lý…') as HTMLInputElement
  expect(input.value).toBe('trạng thái đội')
  expect(send).not.toHaveBeenCalled()
})

test('no stalled/pending chip shows when the board and approvals queries are both empty', async () => {
  wrap()
  await screen.findByText('Đội mình đang thế nào?')
  expect(screen.queryByText('Xem task đang kẹt')).not.toBeInTheDocument()
  expect(screen.queryByText('Duyệt việc đang chờ')).not.toBeInTheDocument()
})

test('a stalled chip and a pending chip appear when the board/approvals data has one', async () => {
  vi.spyOn(api, 'getTeamTaskBoard').mockResolvedValue({
    lanes: [{ id: 'lane-1', cards: [
      { task_id: 't1', title: 'Việc kẹt', pic_id: 'analyst', room_id: 'r1',
        status: 'stalled', created_at: '', steps_done: 1, steps_total: 3 },
    ] }],
  })
  vi.spyOn(api, 'getPendingApprovals').mockResolvedValue({
    pending: [{ id: 1, reason: 'r', status: 'pending', created_at: '', action: {}, agent_id: 'a1' }],
    count: 1,
  })
  wrap()

  await waitFor(() => expect(screen.getByText('Xem task đang kẹt')).toBeInTheDocument())
  expect(screen.getByText('Duyệt việc đang chờ')).toBeInTheDocument()
})
