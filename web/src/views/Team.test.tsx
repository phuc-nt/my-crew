// Team view: pause/resume calls PATCH /enabled, delete requires confirm then calls
// DELETE, and the integration health panel renders ok/fail states. Mocked api (no
// network), matching the rest of the SPA's test style.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { AppProviders } from '../test-utils'
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
  vi.spyOn(api, 'getCompany').mockResolvedValue({
    name: 'Acme Co',
    coordinator_id: null,
    team_task_cap_usd: 2,
  })
})

function wrap(ui: React.ReactElement) {
  return render(
    <AppProviders>
      <MemoryRouter>{ui}</MemoryRouter>
    </AppProviders>,
  )
}

// Render Team inside a router that has landing routes for /chat and /create so we can assert
// where the "+ Tạo nhân sự ảo" button navigates.
function wrapWithRoutes() {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={['/team']}>
        <Routes>
          <Route path="/team" element={<Team />} />
          <Route path="/chat" element={<div>CHAT LANDING</div>} />
          <Route path="/create" element={<div>WIZARD LANDING</div>} />
        </Routes>
      </MemoryRouter>
    </AppProviders>,
  )
}

test('+ Tạo nhân sự ảo → chat when ops-chat is available', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({ available: true, agent_id: 'admin' })
  wrapWithRoutes()
  fireEvent.click(await screen.findByText('+ Tạo nhân sự ảo'))
  await waitFor(() => expect(screen.getByText('CHAT LANDING')).toBeInTheDocument())
})

test('+ Tạo nhân sự ảo → wizard when ops-chat is unavailable (no dead-end, red-team B3)', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({ available: false, reason: 'chưa cấu hình' })
  wrapWithRoutes()
  fireEvent.click(await screen.findByText('+ Tạo nhân sự ảo'))
  await waitFor(() => expect(screen.getByText('WIZARD LANDING')).toBeInTheDocument())
})

test('+ Tạo nhân sự ảo → wizard when the availability check throws', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'opsChatAvailable').mockRejectedValue(new Error('boom'))
  wrapWithRoutes()
  fireEvent.click(await screen.findByText('+ Tạo nhân sự ảo'))
  await waitFor(() => expect(screen.getByText('WIZARD LANDING')).toBeInTheDocument())
})

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
  fireEvent.click(screen.getByText('Tạm dừng'))
  await waitFor(() => expect(setEnabled).toHaveBeenCalledWith('acme', false))
  // the table reflects the RE-FETCHED list, not the optimistic PATCH response
  await waitFor(() => expect(getAgents).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByText('Bật lại')).toBeInTheDocument())
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
  fireEvent.click(screen.getByText('Bật lại'))
  await waitFor(() =>
    expect(screen.getByText(/Agent đang bị tắt trong hồ sơ/)).toBeInTheDocument(),
  )
})

test('+ Tạo trưởng phòng is hidden once a coordinator already exists', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'getCompany').mockResolvedValue({
    name: 'Acme Co',
    coordinator_id: 'truong-phong',
    team_task_cap_usd: 2,
  })
  wrap(<Team />)
  await waitFor(() => expect(screen.getByText('+ Tạo nhân sự ảo')).toBeInTheDocument())
  expect(screen.queryByText('+ Tạo trưởng phòng')).not.toBeInTheDocument()
})

test('+ Tạo trưởng phòng creates the coordinator from the truong-phong template then sets company.coordinator_id', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  const getStaffTemplates = vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({
    templates: [
      {
        role_id: 'truong-phong',
        role: 'Trưởng phòng (Điều phối đội)',
        domain: 'office',
        reports: [],
        bindings_hint: ['slack'],
        persona: 'persona text',
  web_search: false,
  recommended_runtime: 'native',
      },
    ],
  })
  const createAgent = vi.spyOn(api, 'createAgent').mockResolvedValue({
    created: { id: 'truong-phong', domain: 'office', reports: [] },
  })
  const saveCompany = vi.spyOn(api, 'saveCompany').mockResolvedValue({
    name: 'Acme Co',
    coordinator_id: 'truong-phong',
    team_task_cap_usd: 2,
  })
  wrap(<Team />)
  fireEvent.click(await screen.findByText('+ Tạo trưởng phòng'))
  await waitFor(() => expect(getStaffTemplates).toHaveBeenCalled())
  await waitFor(() =>
    expect(createAgent).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'truong-phong', domain: 'office' }),
    ),
  )
  await waitFor(() => expect(saveCompany).toHaveBeenCalledWith('Acme Co', 'truong-phong', 2))
  await waitFor(() => expect(screen.queryByText('+ Tạo trưởng phòng')).not.toBeInTheDocument())
})

test('+ Tạo trưởng phòng surfaces an inline error and stays clickable when template lookup fails', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [] })
  const createAgent = vi.spyOn(api, 'createAgent')
  wrap(<Team />)
  fireEvent.click(await screen.findByText('+ Tạo trưởng phòng'))
  await waitFor(() => expect(screen.getByText(/Lỗi:/)).toBeInTheDocument())
  expect(createAgent).not.toHaveBeenCalled()
  expect(screen.getByText('+ Tạo trưởng phòng')).not.toBeDisabled()
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
  const deleteButtons = screen.getAllByText('Xoá')
  expect(deleteButtons).toHaveLength(1)

  expect(deleteAgent).not.toHaveBeenCalled()
  fireEvent.click(deleteButtons[0])
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Xoá agent acme?')
  fireEvent.click(within(dialog).getByText('Xoá'))
  await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith('acme'))
  await waitFor(() => expect(screen.getByText(/lưu trữ/)).toBeInTheDocument())
})
