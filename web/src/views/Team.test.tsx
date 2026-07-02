// Team view: pause/resume calls PATCH /enabled, delete requires confirm then calls
// DELETE, and the integration health panel renders ok/fail states. Mocked api (no
// network), matching the rest of the SPA's test style.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { Team } from './Team'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getIntegrationHealth').mockResolvedValue({
    checked_at: 0,
    checks: [
      { id: 'openrouter', label: 'OpenRouter (LLM)', ok: true, detail: 'set', hint: '' },
      {
        id: 'slack',
        label: 'Slack browser-token',
        ok: false,
        detail: 'SLACK_XOXC_TOKEN ✗',
        hint: 'Set SLACK_XOXC_TOKEN in .env',
      },
    ],
  })
  vi.spyOn(api, 'getAgentStatus').mockResolvedValue({
    id: 'acme',
    name: 'Acme',
    enabled: true,
    last_run: null,
    budget: { spent: 1, cap: 50, ratio: 0.02 },
    pending_approvals: 0,
  })
})

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

test('renders the health panel ok + fail states', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  wrap(<Team />)
  await waitFor(() => expect(screen.getByText('OpenRouter (LLM)')).toBeInTheDocument())
  expect(screen.getByText('Slack browser-token')).toBeInTheDocument()
  expect(screen.getByText(/Set SLACK_XOXC_TOKEN in .env/)).toBeInTheDocument()
})

test('pause/resume calls PATCH /enabled then refreshes from GET /api/agents', async () => {
  const getAgents = vi
    .spyOn(api, 'getAgents')
    .mockResolvedValueOnce([{ id: 'acme', name: 'Acme', enabled: true, last_run: null }])
    .mockResolvedValueOnce([{ id: 'acme', name: 'Acme', enabled: false, last_run: null }])
  const setEnabled = vi.spyOn(api, 'setAgentEnabled').mockResolvedValue({
    agent_id: 'acme',
    enabled: false,
    effective_enabled: false,
  })
  wrap(<Team />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Pause'))
  await waitFor(() => expect(setEnabled).toHaveBeenCalledWith('acme', false))
  // the table reflects the RE-FETCHED list, not the optimistic PATCH response
  await waitFor(() => expect(getAgents).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByText('Resume')).toBeInTheDocument())
})

test('resume where the profile still vetoes the agent shows an inline notice', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'acme', name: 'Acme', enabled: false, last_run: null },
  ])
  vi.spyOn(api, 'setAgentEnabled').mockResolvedValue({
    agent_id: 'acme',
    enabled: true,
    effective_enabled: false,
  })
  wrap(<Team />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Resume'))
  await waitFor(() =>
    expect(screen.getByText(/Profile still disabled — enable it in Config/)).toBeInTheDocument(),
  )
})

test('delete requires confirm before calling DELETE, and default has no delete button', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'default', name: 'Default', enabled: true, last_run: null },
    { id: 'acme', name: 'Acme', enabled: true, last_run: null },
  ])
  const deleteAgent = vi.spyOn(api, 'deleteAgent').mockResolvedValue({
    agent_id: 'acme',
    deleted: true,
    profile_dir_kept: true,
  })
  wrap(<Team />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  // only one Delete button (for acme, not default)
  const deleteButtons = screen.getAllByText('Delete')
  expect(deleteButtons).toHaveLength(1)

  expect(deleteAgent).not.toHaveBeenCalled()
  fireEvent.click(deleteButtons[0])
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Delete agent acme?')
  fireEvent.click(within(dialog).getByText('Delete'))
  await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith('acme'))
  await waitFor(() => expect(screen.getByText(/archive/)).toBeInTheDocument())
})
