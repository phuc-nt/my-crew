// v7 M18a AgentPage tests: renders status, and binds a Telegram bot from the panel.
// Mocked api, no network. Wrapped in a router (component uses useParams).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { AgentPage } from './AgentPage'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgentStatus').mockResolvedValue({
    id: 'acme',
    name: 'ACME PM',
    enabled: true,
    last_run: { kind: 'daily', status: 'delivered', ts: 't1' },
    budget: { spent: 1, cap: 50, ratio: 0.02 },
    pending_approvals: 0,
  })
  vi.spyOn(api, 'getCost').mockResolvedValue({
    agent_id: 'acme',
    series: [],
    cap: 50,
    warn_ratio: 0.8,
    spent_this_month: 1.5,
  })
  vi.spyOn(api, 'getRuns').mockResolvedValue({ agent_id: 'acme', runs: [] })
})

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/agents/${id}`]}>
      <Routes>
        <Route path="/agents/:id" element={<AgentPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

test('renders agent identity and activity', async () => {
  renderAt('acme')
  await waitFor(() => expect(screen.getByText(/ACME PM/)).toBeInTheDocument())
  expect(screen.getByText('đang bật')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/\$1.5000/)).toBeInTheDocument())
})

test('binds a telegram bot from the panel', async () => {
  const bind = vi
    .spyOn(api, 'bindTelegram')
    .mockResolvedValue({ ok: true, bot_username: 'acme_bot', env_name: 'ACME_TELEGRAM_BOT_TOKEN' })
  renderAt('acme')
  await screen.findByText(/ACME PM/)
  fireEvent.click(screen.getByText('Kênh Telegram'))
  fireEvent.change(await screen.findByPlaceholderText('123456:ABC-...'), {
    target: { value: '123:ABC' },
  })
  fireEvent.change(screen.getByPlaceholderText('5248565986'), { target: { value: '555' } })
  fireEvent.click(screen.getByText('Gắn bot'))
  await waitFor(() => expect(screen.getByText(/Đã gắn bot/)).toBeInTheDocument())
  expect(bind).toHaveBeenCalledWith('acme', '123:ABC', ['555'])
})
