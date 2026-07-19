// v54 P3: cost chip lazy per the v50 desk-inspector pattern — fetched ONLY for the
// selected room (never fanned out over the whole list on mount), cached so re-selection
// doesn't re-fetch.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import type { Workroom } from '../../types'
import { WorkroomList } from './workroom-list'

afterEach(() => {
  vi.restoreAllMocks()
})

const ROOMS: Workroom[] = [
  { room_id: 'r1', title: 'Việc 1', task_count: 1, status: 'dang-chay', updated_at: 't' },
  { room_id: 'r2', title: 'Việc 2', task_count: 1, status: 'xong', updated_at: 't' },
]

test('mounting the list with no selected room fetches no cost at all', () => {
  const costSpy = vi.spyOn(api, 'getTeamTaskCost')
  render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom={null} onSelect={() => {}} />
    </LanguageProvider>,
  )
  expect(costSpy).not.toHaveBeenCalled()
})

test('selecting a room fetches cost for that room only, not the others', async () => {
  const costSpy = vi.spyOn(api, 'getTeamTaskCost').mockResolvedValue({
    task_id: 'r1', total_cost_usd: 1.5, total_input_tokens: 10, total_output_tokens: 5, steps: [],
  })
  render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom="r1" onSelect={() => {}} />
    </LanguageProvider>,
  )
  await waitFor(() => expect(screen.getByText('$1.50')).toBeTruthy())
  expect(costSpy).toHaveBeenCalledTimes(1)
  expect(costSpy).toHaveBeenCalledWith('r1')
})

test('re-rendering with the same active room does not re-fetch (cached)', async () => {
  const costSpy = vi.spyOn(api, 'getTeamTaskCost').mockResolvedValue({
    task_id: 'r1', total_cost_usd: 0.25, total_input_tokens: 10, total_output_tokens: 5, steps: [],
  })
  const { rerender } = render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom="r1" onSelect={() => {}} />
    </LanguageProvider>,
  )
  await waitFor(() => expect(screen.getByText('$0.2500')).toBeTruthy())
  rerender(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom="r1" onSelect={() => {}} />
    </LanguageProvider>,
  )
  await waitFor(() => expect(costSpy).toHaveBeenCalledTimes(1))
})

test('switching the selected room fetches the newly selected room', async () => {
  const costSpy = vi.spyOn(api, 'getTeamTaskCost')
    .mockResolvedValueOnce({
      task_id: 'r1', total_cost_usd: 1, total_input_tokens: 1, total_output_tokens: 1, steps: [],
    })
    .mockResolvedValueOnce({
      task_id: 'r2', total_cost_usd: 2, total_input_tokens: 1, total_output_tokens: 1, steps: [],
    })
  const { rerender } = render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom="r1" onSelect={() => {}} />
    </LanguageProvider>,
  )
  await waitFor(() => expect(screen.getByText('$1.00')).toBeTruthy())
  rerender(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom="r2" onSelect={() => {}} />
    </LanguageProvider>,
  )
  await waitFor(() => expect(screen.getByText('$2.00')).toBeTruthy())
  expect(costSpy).toHaveBeenCalledTimes(2)
  expect(costSpy).toHaveBeenNthCalledWith(1, 'r1')
  expect(costSpy).toHaveBeenNthCalledWith(2, 'r2')
})

test('a cost fetch failure never blocks room selection (no chip, no throw)', async () => {
  vi.spyOn(api, 'getTeamTaskCost').mockRejectedValue(new Error('network'))
  const onSelect = vi.fn()
  render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom="r1" onSelect={onSelect} />
    </LanguageProvider>,
  )
  fireEvent.click(screen.getByText('Việc 2', { exact: false }))
  expect(onSelect).toHaveBeenCalledWith('r2')
  expect(screen.queryByText(/^\$/)).toBeNull()
})
