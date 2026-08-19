// The agent tabs that absorbed /cost, /guardrail, /memory, /timeline and /config.
//
// These assertions came from the deleted per-route view tests and are kept verbatim in
// intent: the e2e only proves the tabs EXIST, so this is the only place that proves the
// backend's data actually reaches them — including the one behaviour a config editor must
// never lose, that a rejected profile.yaml shows the server's own words.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ApiError, api } from '../../../api/client'
import { AppProviders } from '../../../test-utils'
import { ActivityTab } from './activity-tab'
import { AdvancedTab } from './advanced-tab'
import { BudgetCostTab } from './budget-cost-tab'
import { MemoryTab } from './memory-tab'

// Stub the chart wrappers — Chart.js needs a real canvas; we only care the data arrives.
vi.mock('../../../components/charts/CostChart', () => ({
  CostChart: ({ series }: { series: unknown[] }) => (
    <div data-testid="cost-chart">{series.length} months</div>
  ),
}))
vi.mock('../../../components/charts/VerdictChart', () => ({
  VerdictChart: ({ counts }: { counts: Record<string, number> }) => (
    <div data-testid="verdict-chart">{Object.keys(counts).length} verdicts</div>
  ),
}))

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'acme', name: 'Acme', enabled: true, last_run: null },
  ])
})

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

test('budget tab renders the monthly series + ratio', async () => {
  vi.spyOn(api, 'getCost').mockResolvedValue({
    agent_id: 'acme',
    series: [
      { month: '2026-05', total_usd: 3.5 },
      { month: '2026-06', total_usd: 1.2 },
    ],
    cap: 50,
    warn_ratio: 0.8,
    spent_this_month: 1.2,
  })
  vi.spyOn(api, 'getAudit').mockResolvedValue({ agent_id: 'acme', counts: {}, recent: [] })
  wrap(<BudgetCostTab id="acme" />)
  await waitFor(() => expect(screen.getByTestId('cost-chart')).toHaveTextContent('2 months'))
  expect(screen.getByText(/trên hạn mức \$50.00/)).toBeInTheDocument()
})

test('budget tab renders verdict counts + recent gateway rows', async () => {
  vi.spyOn(api, 'getCost').mockResolvedValue({
    agent_id: 'acme',
    series: [],
    cap: 50,
    warn_ratio: 0.8,
    spent_this_month: 0,
  })
  vi.spyOn(api, 'getAudit').mockResolvedValue({
    agent_id: 'acme',
    counts: { allow: 3, deny: 1 },
    recent: [{ timestamp: 't1', action_type: 'mcp_tool', tool: 'slack:post', verdict: 'allow' }],
  })
  wrap(<BudgetCostTab id="acme" />)
  await waitFor(() => expect(screen.getByTestId('verdict-chart')).toHaveTextContent('2 verdicts'))
  expect(screen.getByText('slack:post')).toBeInTheDocument()
})

test('activity tab lists run history', async () => {
  vi.spyOn(api, 'getRuns').mockResolvedValue({
    agent_id: 'acme',
    runs: [{ ts: 't1', kind: 'daily', audience: 'internal', status: 'delivered', delivered: true }],
  })
  vi.spyOn(api, 'getCaptures').mockResolvedValue({ captures: [] })
  wrap(<ActivityTab id="acme" />)
  await waitFor(() => expect(screen.getByText('Báo cáo hằng ngày')).toBeInTheDocument())
  expect(screen.getByText('đã gửi')).toBeInTheDocument()
})

test('memory tab shows the empty notice for both halves', async () => {
  vi.spyOn(api, 'getMemory').mockResolvedValue({ agent_id: 'acme', facts: [], internal_only: true })
  vi.spyOn(api, 'getAutomation').mockResolvedValue({ agent_id: 'acme', pending: [] })
  wrap(<MemoryTab id="acme" />)
  await waitFor(() => expect(screen.getByText(/Chưa ghi nhớ điều gì/)).toBeInTheDocument())
  expect(screen.getByText(/Không có đề xuất chờ duyệt/)).toBeInTheDocument()
})

test('memory tab renders a seeded fact + proposal', async () => {
  vi.spyOn(api, 'getMemory').mockResolvedValue({
    agent_id: 'acme',
    facts: [{ fact: 'SCRUM-15 overdue', ts: 't1', key: 'k1' }],
    internal_only: true,
  })
  vi.spyOn(api, 'getAutomation').mockResolvedValue({
    agent_id: 'acme',
    pending: [
      {
        id: 1,
        reason: 'external post',
        status: 'pending',
        created_at: 't1',
        action_summary: 'mcp_tool:slack:post_message',
      },
    ],
  })
  wrap(<MemoryTab id="acme" />)
  await waitFor(() => expect(screen.getByText('SCRUM-15 overdue')).toBeInTheDocument())
  expect(screen.getByText('mcp_tool:slack:post_message')).toBeInTheDocument()
})

test('advanced tab surfaces the backend validation error verbatim', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'name: acme', soul: 's', project: 'p', memory: 'm' },
  })
  vi.spyOn(api, 'saveProfile').mockRejectedValue(
    new ApiError(400, 'profile.yaml must be a YAML mapping'),
  )
  wrap(<AdvancedTab id="acme" />)
  await waitFor(() => expect(screen.getByText('profile.yaml')).toBeInTheDocument())
  // the first Save button is profile.yaml's
  fireEvent.click(screen.getAllByText('Lưu')[0])
  await waitFor(() => expect(screen.getByText(/must be a YAML mapping/)).toBeInTheDocument())
})

test('MEMORY.md editor stays read-only (no Save button)', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'p', soul: 's', project: 'pr', memory: 'agent memory' },
  })
  wrap(<AdvancedTab id="acme" />)
  await waitFor(() => expect(screen.getByText(/MEMORY.md \(chỉ đọc\)/)).toBeInTheDocument())
  // profile/soul/project each have a Save → 3, not 4 (memory has none)
  expect(screen.getAllByText('Lưu')).toHaveLength(3)
})
