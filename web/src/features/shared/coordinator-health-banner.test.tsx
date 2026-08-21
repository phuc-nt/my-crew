// The banner must render the SERVER-supplied hint (not a hardcoded checkout-dev command)
// so a launchd/container/systemd install shows its own correct restart instruction.
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import { CoordinatorHealthBanner } from './coordinator-health-banner'

afterEach(() => {
  vi.restoreAllMocks()
})

function renderBanner() {
  return render(
    <LanguageProvider>
      <CoordinatorHealthBanner />
    </LanguageProvider>,
  )
}

test('renders nothing while the coordinator is alive', async () => {
  vi.spyOn(api, 'getCoordinatorHealth').mockResolvedValue({
    alive: true, last_beat_ago_s: 5, reason: '', hint: '',
  })
  const { container } = renderBanner()
  await waitFor(() => expect(api.getCoordinatorHealth).toHaveBeenCalled())
  expect(container.querySelector('.office-health-banner')).toBeNull()
})

test('renders the no_coordinator warning without a hint code block', async () => {
  vi.spyOn(api, 'getCoordinatorHealth').mockResolvedValue({
    alive: false, last_beat_ago_s: null, reason: 'no_coordinator', hint: '',
  })
  renderBanner()
  await waitFor(() =>
    expect(document.querySelector('.office-health-warn')).not.toBeNull(),
  )
})

test('renders the server-supplied hint for a stale coordinator, not a hardcoded command', async () => {
  vi.spyOn(api, 'getCoordinatorHealth').mockResolvedValue({
    alive: false, last_beat_ago_s: 999, reason: 'stale',
    hint: 'Chạy: systemctl restart my-crew-coordinator',
  })
  renderBanner()
  await waitFor(() =>
    expect(screen.getByText('Chạy: systemctl restart my-crew-coordinator')).toBeInTheDocument(),
  )
  expect(screen.queryByText(/uv run python -m my_crew\.runtime\.service/)).toBeNull()
})
