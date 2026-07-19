// v31 P1: fleet activity view — empty state, rows across sources, agent filter refetch.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { DICT } from '../i18n/dictionary'
import { LanguageProvider } from '../i18n/language-context'
import type { CompanyActivityPayload } from '../types'
import { CompanyActivity } from './CompanyActivity'

function renderActivity() {
  return render(
    <LanguageProvider>
      <CompanyActivity />
    </LanguageProvider>,
  )
}

const EMPTY: CompanyActivityPayload = { items: [], agents: ['hr', 'pm'], skipped: [] }

const ROWS: CompanyActivityPayload = {
  agents: ['hr', 'pm'],
  skipped: ['broken'],
  items: [
    {
      ts: '2026-07-12T08:00:00+00:00', agent_id: 'hr', source: 'audit',
      action_type: 'mcp_tool', tool: 'slack:post_message', verdict: 'allow', reason: '',
    },
    {
      ts: '2026-07-12T07:00:00+00:00', agent_id: 'pm', source: 'run',
      kind: 'daily', audience: 'internal', status: 'delivered', delivered: true,
    },
    {
      ts: '2026-07-12T06:00:00+00:00', agent_id: 'pm', source: 'capture',
      task_id: 't1', step_type: 'work', engine: 'native', status: 'done',
    },
  ],
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('shows the empty state when no activity exists', async () => {
  vi.spyOn(api, 'getCompanyActivity').mockResolvedValue(EMPTY)
  renderActivity()
  await waitFor(() =>
    expect(screen.getByText(DICT.vi['companyActivity.empty'])).toBeInTheDocument(),
  )
})

test('renders one row per item across all three sources + skipped notice', async () => {
  vi.spyOn(api, 'getCompanyActivity').mockResolvedValue(ROWS)
  renderActivity()
  await waitFor(() => expect(screen.getByText(/slack:post_message/)).toBeInTheDocument())
  expect(screen.getByText(/chạy 'daily'/)).toBeInTheDocument()
  expect(screen.getByText(/bước work trên native/)).toBeInTheDocument()
  expect(screen.getByText(/Không đọc được dữ liệu của: broken/)).toBeInTheDocument()
})

test('shows the actor tag when the acting agent differs from the log owner (v46)', async () => {
  vi.spyOn(api, 'getCompanyActivity').mockResolvedValue({
    agents: ['pm'], skipped: [],
    items: [
      {
        ts: '2026-07-12T08:00:00+00:00', agent_id: 'pm', source: 'audit',
        action_type: 'mcp_tool', tool: 'slack:post_message', verdict: 'allow', reason: '',
        actor: 'nghien-cuu', // acted under pm's context → tag surfaces the real actor
      },
      {
        ts: '2026-07-12T07:00:00+00:00', agent_id: 'pm', source: 'audit',
        action_type: 'mcp_tool', tool: 'jira:search', verdict: 'allow', reason: '',
        actor: 'pm', // same as owner → no tag
      },
    ],
  })
  renderActivity()
  await waitFor(() => expect(screen.getByText(/\[bởi nghien-cuu\]/)).toBeInTheDocument())
  expect(screen.queryByText(/\[bởi pm\]/)).not.toBeInTheDocument()
})

test('changing the agent filter refetches with agent param', async () => {
  const spy = vi.spyOn(api, 'getCompanyActivity').mockResolvedValue(ROWS)
  renderActivity()
  await waitFor(() => expect(spy).toHaveBeenCalled())
  fireEvent.change(screen.getByLabelText(/Agent/), { target: { value: 'hr' } })
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ agent: 'hr' })),
  )
})
