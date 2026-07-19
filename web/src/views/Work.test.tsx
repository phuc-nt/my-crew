// v7 M20 Work page: aggregates pending approvals across agents + approve/reject; embeds the
// tasks board. Mocked api, no network. Wrapped in a router (uses <Link>).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { DICT } from '../i18n/dictionary'
import { LanguageProvider } from '../i18n/language-context'
import { Work } from './Work'

const APPROVAL = {
  id: 7,
  reason: 'gửi báo cáo ra kênh stakeholder',
  status: 'pending',
  created_at: 't1',
  // real Lớp B action shape (mcp_tool → fields nested in args, camelCase) — red-team M1
  action: { type: 'mcp_tool', server: 'slack', tool: 'post_message', args: { channel: 'ext' } },
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
  vi.spyOn(api, 'getRuns').mockResolvedValue({ agent_id: 'x', runs: [] } as never)
})

function renderWork() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <Work />
      </LanguageProvider>
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
  fireEvent.click(await screen.findByText(DICT.vi['work.reviewAndApprove']))
  fireEvent.click(await screen.findByText('Duyệt & thực hiện'))
  await waitFor(() => expect(approve).toHaveBeenCalledWith('hr', 7))
})

test('reject calls the agent-scoped reject endpoint after a light confirm', async () => {
  // Reject is safe + reversible, so it uses window.confirm (not the full dialog) — v9 P1.
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const reject = vi.spyOn(api, 'reject').mockResolvedValue({ agent_id: 'hr', pending: [] })
  renderWork()
  fireEvent.click(await screen.findByText(DICT.vi['work.reject']))
  await waitFor(() => expect(reject).toHaveBeenCalledWith('hr', 7))
})

test('shows empty state when nothing is pending', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue({ agent_id: 'x', pending: [] })
  renderWork()
  expect(await screen.findByText(new RegExp(DICT.vi['work.emptyApprovals'].slice(0, 20)))).toBeInTheDocument()
})

test('shows the "Đã tự duyệt hôm nay" block when auto-approved runs exist (M23)', async () => {
  const today = new Date().toISOString().slice(0, 10)
  vi.spyOn(api, 'getRuns').mockImplementation(async (id: string) =>
    id === 'hr'
      ? {
          agent_id: 'hr',
          runs: [
            { ts: `${today}T09:30:00+00:00`, kind: 'daily', status: 'delivered', auto_approved: true },
            { ts: `${today}T08:00:00+00:00`, kind: 'okr', status: 'delivered' }, // not auto → excluded
          ],
        }
      : { agent_id: id, runs: [] },
  )
  renderWork()
  expect(await screen.findByText(/Đã tự duyệt hôm nay/)).toBeInTheDocument()
  expect(screen.getByText(/báo cáo daily/)).toBeInTheDocument()
  expect(screen.queryByText(/báo cáo okr/)).not.toBeInTheDocument()
})
