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
  // Knowledge tab (M19) also loads the company-docs picker; default to empty so the
  // existing knowledge/skills assertions aren't disturbed.
  vi.spyOn(api, 'getAgentCompanyDocs').mockResolvedValue({ docs: [] })
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

test('knowledge tab edits SOUL as a form and saves fields', async () => {
  vi.spyOn(api, 'getKnowledge').mockImplementation(async (_id, doc) => ({
    doc,
    raw_mode: false,
    fields:
      doc === 'soul'
        ? { role: 'PM', tone: '', rules: '' }
        : { team: '', conventions: '', notes: '' },
    raw: '',
  }))
  vi.spyOn(api, 'getSkills').mockResolvedValue({ skills: [] })
  const putForm = vi.spyOn(api, 'putKnowledgeForm').mockResolvedValue({ ok: true })

  renderAt('acme')
  await screen.findByText(/ACME PM/)
  fireEvent.click(screen.getByText('Kiến thức'))

  const role = await screen.findByDisplayValue('PM')
  fireEvent.change(role, { target: { value: 'Trợ lý PM' } })
  fireEvent.click(screen.getAllByText('Lưu')[0])
  await waitFor(() =>
    expect(putForm).toHaveBeenCalledWith('acme', 'soul', {
      role: 'Trợ lý PM',
      tone: '',
      rules: '',
    }),
  )
})

test('knowledge tab falls back to raw editor when file lost its markers', async () => {
  vi.spyOn(api, 'getKnowledge').mockImplementation(async (_id, doc) => ({
    doc,
    raw_mode: doc === 'soul',
    fields: doc === 'soul' ? {} : { team: '', conventions: '', notes: '' },
    raw: doc === 'soul' ? '# SOUL\nviết tay\n' : '',
  }))
  vi.spyOn(api, 'getSkills').mockResolvedValue({ skills: [] })
  const putRaw = vi.spyOn(api, 'putKnowledgeRaw').mockResolvedValue({ ok: true })

  renderAt('acme')
  await screen.findByText(/ACME PM/)
  fireEvent.click(screen.getByText('Kiến thức'))

  const raw = await screen.findByDisplayValue(/viết tay/)
  fireEvent.change(raw, { target: { value: '# SOUL\nsửa raw\n' } })
  fireEvent.click(screen.getAllByText('Lưu')[0])
  await waitFor(() => expect(putRaw).toHaveBeenCalledWith('acme', 'soul', '# SOUL\nsửa raw\n'))
})

test('skills picker toggles and saves selected names', async () => {
  vi.spyOn(api, 'getKnowledge').mockResolvedValue({
    doc: 'soul',
    raw_mode: false,
    fields: { role: '', tone: '', rules: '' },
    raw: '',
  })
  vi.spyOn(api, 'getSkills').mockResolvedValue({
    skills: [
      { name: 'daily-standup', description: 'báo cáo hằng ngày', selected: false },
      { name: 'sprint-report', description: 'báo cáo sprint', selected: true },
    ],
  })
  const putSkills = vi.spyOn(api, 'putSkills').mockResolvedValue({ ok: true, skills: [] })

  renderAt('acme')
  await screen.findByText(/ACME PM/)
  fireEvent.click(screen.getByText('Kiến thức'))

  fireEvent.click(await screen.findByText('daily-standup'))
  fireEvent.click(screen.getByText('Lưu kỹ năng'))
  await waitFor(() => expect(putSkills).toHaveBeenCalled())
  const names = putSkills.mock.calls[0][1] as string[]
  expect(new Set(names)).toEqual(new Set(['sprint-report', 'daily-standup']))
})
