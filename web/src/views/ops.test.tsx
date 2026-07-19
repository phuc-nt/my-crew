// S4 ops view tests: approve requires the confirm step + calls the real endpoint; config save
// surfaces the backend validation error. Mocked api (no network). Local-only (npm test).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { AgentProvider } from '../agent-context'
import { ApiError, api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Approvals } from './Approvals'
import { Config } from './Config'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'acme', name: 'Acme', enabled: true, last_run: null },
  ])
})

function wrap(ui: React.ReactElement) {
  return render(
    <LanguageProvider>
      <AgentProvider>{ui}</AgentProvider>
    </LanguageProvider>,
  )
}

const PENDING = {
  agent_id: 'acme',
  pending: [
    {
      id: 7,
      reason: 'external post',
      status: 'pending',
      created_at: 't1',
      action: { type: 'mcp_tool', server: 'slack', tool: 'post_message', args: { channel: 'C' } },
    },
  ],
}

test('approve requires the two-step confirm before calling the endpoint', async () => {
  vi.spyOn(api, 'getApprovals').mockResolvedValue(PENDING)
  const approve = vi.spyOn(api, 'approve').mockResolvedValue({ agent_id: 'acme', pending: [] })
  wrap(<Approvals />)
  await waitFor(() => expect(screen.getByText('external post')).toBeInTheDocument())

  // approve is NOT called just by listing — the operator must Review → confirm first.
  expect(approve).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Xem & duyệt'))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Duyệt việc #7')
  // the confirm dialog keeps the exact action JSON that will post (in <details>)
  expect(dialog).toHaveTextContent('post_message')
  fireEvent.click(screen.getByText('Duyệt & thực hiện'))
  await waitFor(() => expect(approve).toHaveBeenCalledWith('acme', 7))
})

test('reject calls the reject endpoint after a light confirm', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.spyOn(api, 'getApprovals').mockResolvedValue(PENDING)
  const reject = vi.spyOn(api, 'reject').mockResolvedValue({ agent_id: 'acme', pending: [] })
  wrap(<Approvals />)
  await waitFor(() => expect(screen.getByText('external post')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Từ chối'))
  await waitFor(() => expect(reject).toHaveBeenCalledWith('acme', 7))
})

test('config save surfaces the backend validation error (exact message)', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'name: acme', soul: 's', project: 'p', memory: 'm' },
  })
  vi.spyOn(api, 'saveProfile').mockRejectedValue(
    new ApiError(400, 'profile.yaml must be a YAML mapping'),
  )
  wrap(<Config />)
  await waitFor(() => expect(screen.getByText('profile.yaml')).toBeInTheDocument())
  // the first Save button is profile.yaml's
  fireEvent.click(screen.getAllByText('Lưu')[0])
  await waitFor(() =>
    expect(screen.getByText(/must be a YAML mapping/)).toBeInTheDocument(),
  )
})

test('MEMORY.md editor is read-only (no Save button)', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'p', soul: 's', project: 'pr', memory: 'agent memory' },
  })
  wrap(<Config />)
  await waitFor(() => expect(screen.getByText(/MEMORY.md \(chỉ đọc\)/)).toBeInTheDocument())
  // profile/soul/project each have a Save → 3 Save buttons, not 4 (memory has none)
  expect(screen.getAllByText('Lưu')).toHaveLength(3)
})
