// Số liệu tab: four panels off four queries, one toolbar. Load-bearing:
// - the day window lives in the URL and feeds the tool/engine queries (a "30 days" link
//   must fetch 30 days, not the default);
// - the budget hero badge follows the ratio (ok / near / over) and the per-agent table
//   still marks only over-cap cells with `.error` (the e2e smoke counts them);
// - a panel whose aggregate fails shows its own error line while the others render;
// - Refresh refetches every panel.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
import type {
  EngineCostsPayload, FleetBudgetPayload, RouteStatsPayload, ToolStatsPayload,
} from '../../types'
import { InsightsTab } from './insights-tab'

const BUDGET: FleetBudgetPayload = {
  agents: [
    { agent_id: 'ke-toan', spent_usd: 2.5, cap_usd: 5, ratio: 0.5 },
    { agent_id: 'tro-ly-pm', spent_usd: 12, cap_usd: 10, ratio: 1.2 },
  ],
  total_spent_usd: 14.5, total_cap_usd: 15, ratio: 0.97,
}
const ROUTES: RouteStatsPayload = {
  total: 3,
  by_mode: [{ id: 'sprint', label: 'chạy nhanh (1 người)', count: 2 }, { id: 'team', label: 'cả đội', count: 1 }],
  by_source: [{ id: 'heuristic', label: 'máy đoán', count: 3 }],
  by_shape: [],
  by_effort: [{ id: 'low', label: 'nhẹ', count: 2, dead_ends: 1 }],
  by_failure: [{ id: 'cost_cap_exhausted', label: 'hết tiền', count: 1, group: 'cost_cap', group_label: 'trần chi phí' }],
  failure_groups: [{ id: 'cost_cap', label: 'trần chi phí', count: 1 }],
  failed: 1, dead_ends: 1, downgrades: 0,
}
const TOOLS: ToolStatsPayload = {
  days: 7,
  tools: [{ tool: 'jira.issues', total_calls: 4, successes: 2, failures: 1, denied: 1,
    avg_duration_ms: 120, failure_rate: 0.5, common_errors: [{ reason: 'ngoài giờ', count: 1 }] }],
  agents: ['ke-toan'], skipped: ['ghost'],
}
const ENGINES: EngineCostsPayload = {
  days: 7,
  engines: [
    { engine: 'native', calls: 2, failed: 1, cost_usd: 0.04, input_tokens: 200, output_tokens: 40, avg_duration_ms: 2000 },
    { engine: 'create_agent', calls: 1, failed: 0, cost_usd: 0.01, input_tokens: 100, output_tokens: 20, avg_duration_ms: null },
  ],
  total_cost_usd: 0.05, total_calls: 3,
}

function wrap(url = '/system?tab=insights') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AppProviders>
        <MemoryRouter initialEntries={[url]}>
          <InsightsTab />
        </MemoryRouter>
      </AppProviders>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getFleetBudget').mockResolvedValue(BUDGET)
  vi.spyOn(api, 'getRouteStats').mockResolvedValue(ROUTES)
  vi.spyOn(api, 'getToolStats').mockResolvedValue(TOOLS)
  vi.spyOn(api, 'getEngineCosts').mockResolvedValue(ENGINES)
})

test('budget hero shows the near-cap badge, and only over-cap agent cells carry .error', async () => {
  wrap()
  const status = await screen.findByTestId('budget-status')
  expect(status.textContent).toBe('Sắp chạm hạn mức')
  const budget = screen.getByTestId('insights-budget')
  expect(budget.querySelectorAll('td.error')).toHaveLength(1)
  expect(within(budget).getByRole('link', { name: 'ke-toan' })).toHaveAttribute('href', '/team/ke-toan?tab=budget')
  // The fleet bar is a real progressbar at the ratio's percentage.
  expect(within(budget).getByRole('progressbar', { name: 'Tỷ lệ dùng hạn mức toàn đội' }))
    .toHaveAttribute('aria-valuenow', '97')
})

test('the day window in the URL feeds the tool and engine queries', async () => {
  wrap('/system?tab=insights&days=30')
  await screen.findByTestId('budget-status')
  await waitFor(() => expect(api.getToolStats).toHaveBeenCalledWith(30))
  expect(api.getEngineCosts).toHaveBeenCalledWith(30)
  expect(screen.getByRole('button', { name: '30 ngày' })).toHaveAttribute('aria-pressed', 'true')
})

test('an unknown ?days= falls back to the default week', async () => {
  wrap('/system?tab=insights&days=999')
  await screen.findByTestId('budget-status')
  await waitFor(() => expect(api.getToolStats).toHaveBeenCalledWith(7))
})

test('picking a window rewrites the query and refetches with it', async () => {
  wrap()
  await screen.findByTestId('budget-status')
  fireEvent.click(screen.getByRole('button', { name: '90 ngày' }))
  await waitFor(() => expect(api.getToolStats).toHaveBeenCalledWith(90))
  expect(api.getEngineCosts).toHaveBeenCalledWith(90)
})

test('routing, engine and tool panels render the aggregates with backend labels', async () => {
  wrap()
  const routing = screen.getByTestId('insights-routing')
  await within(routing).findByText('chạy nhanh (1 người)')
  expect(within(routing).getByText('2 · 1 chuyển đội')).toBeInTheDocument()
  expect(within(routing).getByText('1 · trần chi phí')).toBeInTheDocument()

  const engines = screen.getByTestId('insights-engines')
  await within(engines).findByText('native')
  // 0.04 of 0.05 → 80 % share bar.
  expect(within(engines).getByRole('progressbar', { name: 'native' })).toHaveAttribute('aria-valuenow', '80')
  expect(within(engines).getByText('—')).toBeInTheDocument() // null avg duration

  const tools = screen.getByTestId('insights-tools')
  await within(tools).findByText('jira.issues')
  expect(within(tools).getByText('50%')).toBeInTheDocument()
  expect(within(tools).getByText('1× ngoài giờ')).toBeInTheDocument()
  expect(within(tools).getByText('Bỏ qua nhân sự không đọc được: ghost')).toBeInTheDocument()
})

test('one failing aggregate shows its own error line while the others render', async () => {
  vi.spyOn(api, 'getToolStats').mockRejectedValue(new Error('boom'))
  wrap()
  await screen.findByTestId('budget-status')
  const tools = screen.getByTestId('insights-tools')
  await within(tools).findByText('Không tải được số liệu công cụ.')
  await within(screen.getByTestId('insights-routing')).findByText('cả đội')
})

test('empty aggregates render their empty lines, not empty tables', async () => {
  vi.spyOn(api, 'getRouteStats').mockResolvedValue({ ...ROUTES, total: 0, by_mode: [], failed: 0, dead_ends: 0 })
  vi.spyOn(api, 'getToolStats').mockResolvedValue({ days: 7, tools: [], agents: [], skipped: [] })
  vi.spyOn(api, 'getEngineCosts').mockResolvedValue({ days: 7, engines: [], total_cost_usd: 0, total_calls: 0 })
  wrap()
  await screen.findByText('Chưa có bản ghi định tuyến nào — giao việc đầu tiên để bắt đầu.')
  expect(screen.getByText('Không có lượt gọi công cụ nào trong khoảng này.')).toBeInTheDocument()
  expect(screen.getByText('Chưa có lượt chạy nào trong khoảng này.')).toBeInTheDocument()
  // Only the budget table exists → its 2 agent rows + header.
  expect(screen.getAllByRole('row')).toHaveLength(3)
})

test('Refresh refetches every panel', async () => {
  wrap()
  await screen.findByTestId('insights-updated')
  fireEvent.click(screen.getByRole('button', { name: 'Làm mới' }))
  await waitFor(() => expect(api.getFleetBudget).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(api.getRouteStats).toHaveBeenCalledTimes(2))
  expect(api.getToolStats).toHaveBeenCalledTimes(2)
  expect(api.getEngineCosts).toHaveBeenCalledTimes(2)
})
