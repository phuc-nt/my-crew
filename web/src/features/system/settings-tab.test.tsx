// v88 P5-D: autopilot toggle + concurrency input on the Settings tab. Chịu lực: toggling
// autopilot POSTs the full field set (unchanged auto-confirm/cap re-sent, autopilot
// flipped); setting concurrency does the same with only concurrency changed — neither
// save silently resets a field the CEO didn't touch (same F7 posture the auto-confirm
// toggle already has).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
import type { CompanyPayload } from '../../types'
import { SettingsTab } from './settings-tab'

const COMPANY: CompanyPayload = {
  name: 'Acme',
  coordinator_id: 'coord-1',
  team_task_cap_usd: 5,
  team_task_concurrency: 3,
  team_task_auto_confirm: false,
  autopilot: false,
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AppProviders>
        <SettingsTab />
      </AppProviders>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getCompany').mockResolvedValue(COMPANY)
  vi.spyOn(api, 'getMe').mockResolvedValue({ authenticated: true, auth: 'disabled' })
})

test('toggling autopilot posts the full field set with autopilot flipped', async () => {
  const save = vi.spyOn(api, 'saveCompany').mockResolvedValue({ ...COMPANY, autopilot: true })
  wrap()
  // The checkbox's label text is static (renders before `company` loads); wait for the
  // company query to resolve (`disabled` clears) before interacting, or the click lands
  // while `toggleAutopilot`'s `if (!company) return` guard is still active.
  const checkbox = await screen.findByLabelText<HTMLInputElement>(
    'Autopilot — thư ký toàn quyền quyết thay',
  )
  await waitFor(() => expect(checkbox).not.toBeDisabled())
  fireEvent.click(checkbox)
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith('Acme', 'coord-1', 5, false, { autopilot: true }),
  )
})

test('setting concurrency posts the full field set with the new value', async () => {
  const save = vi.spyOn(api, 'saveCompany').mockResolvedValue({ ...COMPANY, team_task_concurrency: 7 })
  wrap()
  const input = await screen.findByLabelText<HTMLInputElement>(
    'Số việc chạy song song tối đa (1–10)',
  )
  await waitFor(() => expect(input).not.toBeDisabled())
  fireEvent.change(input, { target: { value: '7' } })
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith('Acme', 'coord-1', 5, false, { teamTaskConcurrency: 7 }),
  )
})
