// First component test: Overview renders the agent list from mocked api data (no network).
// Local-only (npm test in web/), NOT part of the backend pytest gate.
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { AgentProvider } from '../agent-context'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Overview } from './Overview'

function renderOverview() {
  return render(
    <LanguageProvider>
      <AgentProvider>
        <Overview />
      </AgentProvider>
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('renders the agent list from /api/agents', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'acme', name: 'Acme PM', enabled: true, last_run: { kind: 'daily', status: 'delivered' } },
    { id: 'beta', name: 'Beta PM', enabled: false, last_run: null },
  ])
  renderOverview()
  await waitFor(() => expect(screen.getByText('Acme PM')).toBeInTheDocument())
  expect(screen.getByText('Beta PM')).toBeInTheDocument()
  expect(screen.getByText('Báo cáo hằng ngày · đã gửi')).toBeInTheDocument()
  expect(screen.getByText('chưa chạy lần nào')).toBeInTheDocument()
})

test('shows an error when the api fails', async () => {
  vi.spyOn(api, 'getAgents').mockRejectedValue(new Error('boom'))
  renderOverview()
  await waitFor(() => expect(screen.getByText(/Lỗi: boom/)).toBeInTheDocument())
})
