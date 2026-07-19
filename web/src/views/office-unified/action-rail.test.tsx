// v54 P2: action rail — approvals + clarify merged queue (1-click, no new write path;
// same api.approve/reject/answerClarify as Work.tsx / clarify-section.tsx) + "Sắp chạy"
// schedule panel. Mocked api throughout (pattern: Layout.test.tsx / clarify-section.test.tsx).
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { PendingApprovalsProvider } from '../../pending-approvals-context'
import { AppProviders } from '../../test-utils'
import { ActionRail } from './action-rail'

function renderRail() {
  return render(
    <AppProviders>
      <PendingApprovalsProvider>
        <ActionRail />
      </PendingApprovalsProvider>
    </AppProviders>,
  )
}

const APPROVAL = {
  id: 1,
  reason: 'gửi báo cáo tuần lên Slack',
  status: 'pending',
  created_at: '2026-07-19T01:00:00+00:00',
  action: { type: 'mcp_tool', server: 'slack', tool: 'send', args: { channel: '#general' } },
}

const CLARIFY_QUESTION = {
  id: 7,
  agent_id: 'nghien-cuu',
  task_id: 'task12345678',
  question: 'Ưu tiên chi phí hay tốc độ?',
  options: ['Chi phí', 'Tốc độ'],
  asked_at: '2026-07-19T02:00:00+00:00',
  expires_at: '2026-07-21T00:00:00+00:00',
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'hr', name: 'HR', enabled: true, last_run: null },
  ] as never)
  vi.spyOn(api, 'getClarifyPending').mockResolvedValue({ questions: [] })
  vi.spyOn(api, 'getScheduleUpcoming').mockResolvedValue({ items: [] })
})

test('approve click calls api.approve with the right agent/approval ids and refreshes', async () => {
  const getApprovals = vi
    .spyOn(api, 'getApprovals')
    .mockResolvedValueOnce({ agent_id: 'hr', pending: [APPROVAL] })
    .mockResolvedValueOnce({ agent_id: 'hr', pending: [] })
  const approve = vi.spyOn(api, 'approve').mockResolvedValue({ agent_id: 'hr', pending: [] })

  renderRail()

  const approveBtn = await screen.findByRole('button', { name: 'Duyệt' })
  fireEvent.click(approveBtn)

  await waitFor(() => expect(approve).toHaveBeenCalledWith('hr', 1))
  await waitFor(() => expect(getApprovals).toHaveBeenCalledTimes(2))
  await waitFor(() =>
    expect(screen.queryByText(/gửi báo cáo tuần lên Slack/)).not.toBeInTheDocument(),
  )
})

test('reject click calls api.reject with the right agent/approval ids', async () => {
  vi.spyOn(api, 'getApprovals')
    .mockResolvedValueOnce({ agent_id: 'hr', pending: [APPROVAL] })
    .mockResolvedValueOnce({ agent_id: 'hr', pending: [] })
  const reject = vi.spyOn(api, 'reject').mockResolvedValue({ agent_id: 'hr', pending: [] })

  renderRail()

  fireEvent.click(await screen.findByRole('button', { name: 'Từ chối' }))
  await waitFor(() => expect(reject).toHaveBeenCalledWith('hr', 1))
})

test('clarify option click answers via api.answerClarify and removes the item', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'hr', pending: [] })
  vi.spyOn(api, 'getClarifyPending')
    .mockResolvedValueOnce({ questions: [CLARIFY_QUESTION] })
    .mockResolvedValueOnce({ questions: [] })
  const answer = vi.spyOn(api, 'answerClarify').mockResolvedValue({ ok: true, id: 7 })

  renderRail()

  fireEvent.click(await screen.findByRole('button', { name: 'Tốc độ' }))
  await waitFor(() => expect(answer).toHaveBeenCalledWith(7, 'Tốc độ'))
  await waitFor(() =>
    expect(screen.queryByText(/Ưu tiên chi phí hay tốc độ\?/)).not.toBeInTheDocument(),
  )
})

test('empty state renders a single confirming line when nothing is pending', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'hr', pending: [] })
  renderRail()

  expect(await screen.findByText('✓ Không có gì chờ')).toBeInTheDocument()
})

test('schedule panel renders upcoming items from api.getScheduleUpcoming', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'hr', pending: [] })
  vi.spyOn(api, 'getScheduleUpcoming').mockResolvedValue({
    items: [
      { agent_id: 'hr', kind: 'daily', next_ts: '2026-07-19T15:00:00+00:00', label: 'hr: daily' },
    ],
  })

  renderRail()

  expect(await screen.findByText(/hr: daily/)).toBeInTheDocument()
})
