// v6 M15b Tasks board tests: renders assigned tasks per agent; cancel calls the endpoint and
// reloads. Mocked api, no network (npm test).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { DICT } from '../i18n/dictionary'
import { LanguageProvider } from '../i18n/language-context'
import { Tasks } from './Tasks'

function renderTasks() {
  return render(
    <LanguageProvider>
      <Tasks />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

const PAYLOAD = {
  agents: [
    {
      agent_id: 'default',
      tasks: [
        {
          id: 1,
          kind: 'watch' as const,
          params: { target: 'pr', number: 45 },
          status: 'open' as const,
          created_at: 't1',
          assigned_by: 'ceo-chat',
          history: [{ ts: 't2', summary: 'PR #45 vẫn mở', cost_usd: null }],
        },
      ],
    },
  ],
}

test('renders tasks and their status', async () => {
  vi.spyOn(api, 'getTasks').mockResolvedValue(PAYLOAD)
  renderTasks()
  await waitFor(() => expect(screen.getByText(/Theo dõi PR #45/)).toBeInTheDocument())
  expect(screen.getByText(DICT.vi['tasks.stateOpen'])).toBeInTheDocument()
  expect(screen.getByText('PR #45 vẫn mở')).toBeInTheDocument()
})

test('cancel calls the endpoint and reloads', async () => {
  vi.spyOn(api, 'getTasks').mockResolvedValue(PAYLOAD)
  const cancel = vi.spyOn(api, 'cancelTask').mockResolvedValue({ status: 'cancelled' })
  renderTasks()
  await screen.findByText(/Theo dõi PR #45/)
  fireEvent.click(screen.getByText(DICT.vi['tasks.cancel']))
  await waitFor(() => expect(cancel).toHaveBeenCalledWith('default', 1))
})

test('empty board shows a hint', async () => {
  vi.spyOn(api, 'getTasks').mockResolvedValue({ agents: [] })
  renderTasks()
  await waitFor(() => expect(screen.getByText(/Chưa có việc nào/)).toBeInTheDocument())
})
