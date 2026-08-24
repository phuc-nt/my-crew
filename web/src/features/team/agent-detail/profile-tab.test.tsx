// v87 P2: dry-run visibility + toggle on the agent's Profile tab — proves the badge
// reflects the effective value (profile vs fleet source) and the toggle round-trips
// through the mutation without needing a page restart to see the flip.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../../api/client'
import { AppProviders } from '../../../test-utils'
import type { AgentStatus } from '../../../types'
import { ProfileTab } from './profile-tab'

const STATUS: AgentStatus = {
  id: 'acme',
  name: 'Acme',
  enabled: true,
  last_run: null,
  budget: { spent: 0, cap: 50, ratio: 0 },
  pending_approvals: 0,
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([{ id: 'acme', name: 'Acme', enabled: true, last_run: null }])
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'p', soul: '', project: 'pr', memory: 'm' },
  })
  vi.spyOn(api, 'getAgentSafety').mockResolvedValue({
    agent_id: 'acme', dry_run: true, dry_run_source: 'fleet',
  })
  vi.spyOn(api, 'getAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme',
    name: 'Acme',
    model: null,
    model_chain: [],
    budget_monthly_usd: 50,
    schedule: {},
    role_models: {},
    advisor_enabled: null,
  })
  vi.spyOn(api, 'getModelCatalog').mockResolvedValue({ models: ['vendor/alpha', 'vendor/zeta'] })
})

/** Clicks the "Sửa" button belonging to the row whose <dt> label matches `label`.
 *  Positional `getAllByText('Sửa')[n]` indices silently retarget a different field the
 *  moment a row is inserted above — this binds each test to the row it means. */
/** The checkbox inside the row whose <dt> label matches `label`. The tab has more than
 *  one toggle, so `getByRole('checkbox')` is ambiguous and would silently bind a test to
 *  whichever row happens to render first. */
function toggleIn(label: string | RegExp): HTMLElement {
  const dd = screen.getByText(label).nextElementSibling
  if (!dd) throw new Error(`no value cell for row ${String(label)}`)
  return within(dd as HTMLElement).getByRole('checkbox')
}

function clickEdit(label: string | RegExp) {
  const dt = screen.getByText(label)
  const dd = dt.nextElementSibling
  if (!dd) throw new Error(`no value cell for row ${String(label)}`)
  const btn = within(dd as HTMLElement).getByText('Sửa')
  fireEvent.click(btn)
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AppProviders>{ui}</AppProviders>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('shows the dry-run badge with its source (fleet default)', async () => {
  vi.spyOn(api, 'getAgentSafety').mockResolvedValue({
    agent_id: 'acme', dry_run: true, dry_run_source: 'fleet',
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(toggleIn('Chế độ diễn tập')).toBeChecked())
  expect(screen.getByText('Diễn tập')).toBeInTheDocument()
  expect(screen.getByText(/theo mặc định hạm đội/)).toBeInTheDocument()
})

test('shows the per-agent override source when profile.yaml has an explicit key', async () => {
  vi.spyOn(api, 'getAgentSafety').mockResolvedValue({
    agent_id: 'acme', dry_run: false, dry_run_source: 'profile',
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(toggleIn('Chế độ diễn tập')).not.toBeChecked())
  expect(screen.getByText('Gửi thật')).toBeInTheDocument()
  expect(screen.getByText(/ghi đè riêng/)).toBeInTheDocument()
})

test('toggling flips dry_run in one click and reflects the new state (no restart needed)', async () => {
  vi.spyOn(api, 'getAgentSafety')
    .mockResolvedValueOnce({ agent_id: 'acme', dry_run: true, dry_run_source: 'fleet' })
    .mockResolvedValueOnce({ agent_id: 'acme', dry_run: false, dry_run_source: 'profile' })
  const setDryRun = vi.spyOn(api, 'setAgentDryRun').mockResolvedValue({
    agent_id: 'acme', dry_run: false, needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(toggleIn('Chế độ diễn tập')).toBeChecked())

  fireEvent.click(toggleIn('Chế độ diễn tập'))

  await waitFor(() => expect(setDryRun).toHaveBeenCalledWith('acme', false))
  await waitFor(() => expect(toggleIn('Chế độ diễn tập')).not.toBeChecked())
  expect(screen.getByText('Gửi thật')).toBeInTheDocument()
})

test('a failed toggle surfaces an error instead of failing silently', async () => {
  vi.spyOn(api, 'getAgentSafety').mockResolvedValue({
    agent_id: 'acme', dry_run: true, dry_run_source: 'fleet',
  })
  vi.spyOn(api, 'setAgentDryRun').mockRejectedValue(new Error('boom'))
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(toggleIn('Chế độ diễn tập')).toBeChecked())

  fireEvent.click(toggleIn('Chế độ diễn tập'))

  await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument())
})

// v88 P4: structured config forms — name/model/model_chain/schedule editable inline.

test('name field: edit, save, and the PATCH carries the new value', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  const editButtons = screen.getAllByText('Sửa')
  fireEvent.click(editButtons[0]) // name is the first editable row

  const input = screen.getByDisplayValue('Acme')
  fireEvent.change(input, { target: { value: 'Acme Renamed' } })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith('acme', { name: 'Acme Renamed' }),
  )
})

test('model field shows the "follow fleet model" placeholder when absent and can be set', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() =>
    expect(screen.getByText('(dùng model chung của công ty)')).toBeInTheDocument(),
  )

  const editButtons = screen.getAllByText('Sửa')
  // Model row is the 2nd editable row (after name).
  fireEvent.click(editButtons[1])

  const input = screen.getByPlaceholderText('vendor/model-name')
  fireEvent.change(input, { target: { value: 'vendor/alpha' } })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith('acme', { model: 'vendor/alpha' }),
  )
})

test('model_chain field: comma-separated input becomes a validated list on save', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() =>
    expect(screen.getByText('(không có, chỉ dùng 1 model)')).toBeInTheDocument(),
  )

  const editButtons = screen.getAllByText('Sửa')
  fireEvent.click(editButtons[2]) // model_chain is the 3rd editable row

  const input = screen.getByPlaceholderText('vendor/primary, vendor/fallback')
  fireEvent.change(input, { target: { value: 'vendor/primary, vendor/fallback ' } })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith('acme', {
      model_chain: ['vendor/primary', 'vendor/fallback'],
    }),
  )
})

test('schedule field: "kind = cron" lines parse into the full-replace map', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('(chưa đặt lịch)')).toBeInTheDocument())

  clickEdit('Lịch chạy') // schedule is the 4th editable row

  const textarea = screen.getByPlaceholderText('weekly_report = 0 9 * * 1')
  fireEvent.change(textarea, { target: { value: 'weekly_report = 0 9 * * 1' } })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith('acme', { schedule: { weekly_report: '0 9 * * 1' } }),
  )
})

test('schedule field: editing one kind preserves every other existing kind (no silent drop)', async () => {
  // The highest-risk invariant of this phase: the backend does a WHOLE-block replace of
  // `schedule`, so the form must submit the COMPLETE current map — editing one cron line
  // must never drop the sibling kinds. Seed an agent that already has two kinds, edit one,
  // and assert BOTH survive in the PATCH body.
  vi.spyOn(api, 'getAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme',
    name: 'Acme',
    model: null,
    model_chain: [],
    budget_monthly_usd: 50,
    schedule: { weekly_report: '0 9 * * 1', daily_digest: '0 8 * * *' },
    role_models: {},
    advisor_enabled: null,
  })
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  clickEdit('Lịch chạy')

  const textarea = screen.getByPlaceholderText('weekly_report = 0 9 * * 1')
  // Change only daily_digest's cron; weekly_report is left untouched in the textarea.
  fireEvent.change(textarea, {
    target: { value: 'weekly_report = 0 9 * * 1\ndaily_digest = 30 7 * * *' },
  })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith('acme', {
      schedule: { weekly_report: '0 9 * * 1', daily_digest: '30 7 * * *' },
    }),
  )
})

test('schedule field: a malformed line surfaces an error without calling the API', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('(chưa đặt lịch)')).toBeInTheDocument())

  clickEdit('Lịch chạy')

  const textarea = screen.getByPlaceholderText('weekly_report = 0 9 * * 1')
  fireEvent.change(textarea, { target: { value: 'not a valid line' } })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() => expect(screen.getByText(/dùng dạng/)).toBeInTheDocument())
  expect(patch).not.toHaveBeenCalled()
})

test('cancelling an edit discards the draft and reverts to the display row', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings')
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  clickEdit('Tên')
  fireEvent.change(screen.getByDisplayValue('Acme'), { target: { value: 'Should Not Save' } })
  fireEvent.click(screen.getByText('Hủy'))

  expect(screen.getByText('Acme')).toBeInTheDocument()
  expect(patch).not.toHaveBeenCalled()
})


// --- role_models + advisor (per-agent model roles / second opinion) ---------

test('role models row shows every configured role, and the empty state when none', async () => {
  vi.spyOn(api, 'getAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', name: 'Acme', model: null, model_chain: [], budget_monthly_usd: 50,
    schedule: {}, role_models: { review: 'vendor/cheap', advisor: 'vendor/advisor' },
    advisor_enabled: null,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() =>
    expect(screen.getByText('review: vendor/cheap · advisor: vendor/advisor')).toBeInTheDocument(),
  )
})

test('role models row: no override reads as "uses the company model", not as blank', async () => {
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() =>
    expect(screen.getByText('(mọi loại việc dùng model chung)')).toBeInTheDocument(),
  )
})

test('role models: editing one role submits the COMPLETE map (whole-block replace)', async () => {
  // Same invariant the schedule row has: the backend replaces the whole `role_models`
  // mapping, so a sibling role missing from the submitted body would silently lose its
  // override — and an override that vanishes is a cost change no one sees until the bill.
  vi.spyOn(api, 'getAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', name: 'Acme', model: null, model_chain: [], budget_monthly_usd: 50,
    schedule: {}, role_models: { review: 'vendor/cheap', content: 'vendor/writer' },
    advisor_enabled: null,
  })
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  clickEdit('Model theo loại việc')
  fireEvent.change(screen.getByPlaceholderText('review = vendor/model-re'), {
    target: { value: 'review = vendor/cheaper\ncontent = vendor/writer' },
  })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() =>
    expect(patch).toHaveBeenCalledWith('acme', {
      role_models: { review: 'vendor/cheaper', content: 'vendor/writer' },
    }),
  )
})

test('role models: clearing the box sends an empty map (drops every override)', async () => {
  vi.spyOn(api, 'getAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', name: 'Acme', model: null, model_chain: [], budget_monthly_usd: 50,
    schedule: {}, role_models: { review: 'vendor/cheap' }, advisor_enabled: null,
  })
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  clickEdit('Model theo loại việc')
  fireEvent.change(screen.getByPlaceholderText('review = vendor/model-re'), {
    target: { value: '' },
  })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() => expect(patch).toHaveBeenCalledWith('acme', { role_models: {} }))
})

test('role models: a malformed line surfaces an error without calling the API', async () => {
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  clickEdit('Model theo loại việc')
  fireEvent.change(screen.getByPlaceholderText('review = vendor/model-re'), {
    target: { value: 'review vendor/cheap' },
  })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() => expect(screen.getByText(/dùng dạng/)).toBeInTheDocument())
  expect(patch).not.toHaveBeenCalled()
})

test("role models: the backend's own role-name error is shown verbatim", async () => {
  // The role name set lives in the backend loader; re-implementing it in the form would
  // let the two drift, so the form shows exactly what the loader said.
  const message = "unknown role_models key 'contnet' — valid roles are advisor, aggregate, content, plan, review, util"
  vi.spyOn(api, 'patchAgentProfileSettings').mockRejectedValue(new Error(message))
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())

  clickEdit('Model theo loại việc')
  fireEvent.change(screen.getByPlaceholderText('review = vendor/model-re'), {
    target: { value: 'contnet = vendor/writer' },
  })
  fireEvent.click(screen.getByText('Lưu'))

  await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument())
})

test('advisor toggle: an absent key reads as inherited, not as an explicit off', async () => {
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
  expect(screen.getByText('(theo mặc định công ty)')).toBeInTheDocument()
  expect(screen.getByText('Tắt')).toBeInTheDocument()
})

test('advisor toggle: an explicit false is NOT shown as inherited', async () => {
  vi.spyOn(api, 'getAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', name: 'Acme', model: null, model_chain: [], budget_monthly_usd: 50,
    schedule: {}, role_models: {}, advisor_enabled: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  // `Tắt` also renders while the query is still in flight (undefined -> null), so waiting
  // on it would assert against the pre-fetch state; wait for a value only the LOADED
  // payload can produce.
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
  await waitFor(() =>
    expect(screen.queryByText('(theo mặc định công ty)')).not.toBeInTheDocument(),
  )
  expect(screen.getByText('Tắt')).toBeInTheDocument()
})

test('advisor toggle: one click turns it on and the row reflects the new state', async () => {
  vi.spyOn(api, 'getAgentProfileSettings')
    .mockResolvedValueOnce({
      agent_id: 'acme', name: 'Acme', model: null, model_chain: [], budget_monthly_usd: 50,
      schedule: {}, role_models: {}, advisor_enabled: null,
    })
    .mockResolvedValue({
      agent_id: 'acme', name: 'Acme', model: null, model_chain: [], budget_monthly_usd: 50,
      schedule: {}, role_models: {}, advisor_enabled: true,
    })
  const patch = vi.spyOn(api, 'patchAgentProfileSettings').mockResolvedValue({
    agent_id: 'acme', needs_restart: false,
  })
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('(theo mặc định công ty)')).toBeInTheDocument())

  fireEvent.click(toggleIn('Cố vấn theo sát')) // dry-run is [0], advisor is [1]

  await waitFor(() => expect(patch).toHaveBeenCalledWith('acme', { advisor_enabled: true }))
  await waitFor(() => expect(screen.getByText('Bật')).toBeInTheDocument())
})

test('advisor toggle: a failed flip surfaces an error instead of failing silently', async () => {
  vi.spyOn(api, 'patchAgentProfileSettings').mockRejectedValue(new Error('boom'))
  wrap(<ProfileTab id="acme" status={STATUS} />)
  await waitFor(() => expect(screen.getByText('(theo mặc định công ty)')).toBeInTheDocument())

  fireEvent.click(toggleIn('Cố vấn theo sát'))

  await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument())
})
