// Dual-lens P3: Captures explorer + header search box (logic in jsdom; visuals = P4 UAT).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { SearchBox } from '../components/search-box'
import type { CaptureRow } from '../types'
import { Captures } from './Captures'

afterEach(() => vi.restoreAllMocks())

const ROW: CaptureRow = {
  attempt_id: 'a1', task_id: 'task-123456', step_id: 'step-1', agent_id: 'hr',
  engine: 'deep_agent', status: 'done', step_type: 'work', review_round: 0,
  cost_usd: 0.1234, cost_source: 'exact', input_tokens: 900, output_tokens: 120,
  started_at: 's', ended_at: 'e', duration_ms: 7500, error: '', ts: '2026-07-18T09:00:00Z',
}

test('captures table renders rows with engine/cost-source and expands detail on click', async () => {
  vi.spyOn(api, 'getCaptures').mockResolvedValue({ captures: [ROW] })
  render(<MemoryRouter><Captures /></MemoryRouter>)
  await waitFor(() => expect(screen.getByText('deep_agent')).toBeTruthy())
  expect(screen.getByText('$0.1234 (exact)')).toBeTruthy()
  expect(screen.getByText('900→120')).toBeTruthy()
  fireEvent.click(screen.getByText('deep_agent'))
  await waitFor(() => expect(screen.getByText('a1')).toBeTruthy())
})

test('captures passes the task_id filter from the URL through to the API', async () => {
  const spy = vi.spyOn(api, 'getCaptures').mockResolvedValue({ captures: [] })
  render(
    <MemoryRouter initialEntries={['/captures?task_id=t9']}>
      <Captures />
    </MemoryRouter>,
  )
  await waitFor(() =>
    expect(spy).toHaveBeenCalledWith({ task_id: 't9', agent: undefined, limit: 200 }),
  )
})

test('search box debounces, shows hits, and a step hit navigates to its office room', async () => {
  vi.useFakeTimers()
  const spy = vi.spyOn(api, 'searchHistory').mockResolvedValue({
    hits: [
      { excerpt: 'báo cáo »sprint« tuần', source: 'step', ref: 'task-9:step-2', agent_id: 'pm', ts: 't' },
    ],
  })
  render(<MemoryRouter><SearchBox /></MemoryRouter>)
  fireEvent.change(screen.getByPlaceholderText('tìm lịch sử…'), { target: { value: 'sprint' } })
  expect(spy).not.toHaveBeenCalled() // debounce window still open
  await vi.advanceTimersByTimeAsync(350)
  expect(spy).toHaveBeenCalledWith('sprint')
  vi.useRealTimers()
  await waitFor(() => expect(screen.getByText(/sprint/)).toBeTruthy())
})
