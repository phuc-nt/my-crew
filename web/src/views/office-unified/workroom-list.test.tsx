// v54 P3: cost chip lazy per the v50 desk-inspector pattern — fetched ONLY for the
// selected room (never fanned out over the whole list on mount), cached so re-selection
// doesn't re-fetch.
// v55: default status filter shows ● + ⚠ only (✓ off), title search ignores the filter,
// recurring identical-title runs collapse into a ×N group row.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { DICT } from '../../i18n/dictionary'
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
  // 'Việc 2' is xong — hidden by the default filter; enable ✓ first (chip titled Xong).
  fireEvent.click(screen.getByTitle(DICT.vi['workroomList.filter.xong']))
  fireEvent.click(screen.getByText('Việc 2', { exact: false }))
  expect(onSelect).toHaveBeenCalledWith('r2')
  expect(screen.queryByText(/^\$/)).toBeNull()
})

test('v55 default filter: xong rooms hidden until the ✓ chip is toggled on', () => {
  render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom={null} onSelect={() => {}} />
    </LanguageProvider>,
  )
  expect(screen.getByText('Việc 1', { exact: false })).toBeTruthy()
  expect(screen.queryByText('Việc 2', { exact: false })).toBeNull()
  expect(screen.getByText(DICT.vi['workroomList.hiddenHint'].replace('{n}', '1'))).toBeTruthy()
  fireEvent.click(screen.getByTitle(DICT.vi['workroomList.filter.xong']))
  expect(screen.getByText('Việc 2', { exact: false })).toBeTruthy()
})

test('v55 search ignores the status filter and matches by substring', () => {
  render(
    <LanguageProvider>
      <WorkroomList rooms={ROOMS} activeRoom={null} onSelect={() => {}} />
    </LanguageProvider>,
  )
  fireEvent.change(screen.getByPlaceholderText(DICT.vi['workroomList.searchPlaceholder']), {
    target: { value: 'việc 2' },
  })
  expect(screen.getByText('Việc 2', { exact: false })).toBeTruthy()
  expect(screen.queryByText('Việc 1', { exact: false })).toBeNull()
})

test('v55 recurring runs collapse into a ×N group row and expand on click', () => {
  const watchRooms: Workroom[] = [
    { room_id: 'w2', title: '[watch] đổi Jira', task_count: 1, status: 'dang-chay', updated_at: 't2' },
    { room_id: 'w1', title: '[watch] đổi Jira', task_count: 1, status: 'dang-chay', updated_at: 't1' },
  ]
  const onSelect = vi.fn()
  render(
    <LanguageProvider>
      <WorkroomList rooms={watchRooms} activeRoom={null} onSelect={onSelect} />
    </LanguageProvider>,
  )
  // Collapsed: only the group row itself carries the shared title.
  expect(screen.getAllByTitle('[watch] đổi Jira').length).toBe(1)
  fireEvent.click(screen.getByText(/×2/))
  // Expanded: group row + two run chips (newest first), each selectable.
  const runs = screen.getAllByTitle('[watch] đổi Jira').filter((el) => el.getAttribute('aria-expanded') === null)
  expect(runs.length).toBe(2)
  fireEvent.click(runs[0])
  expect(onSelect).toHaveBeenCalledWith('w2')
})
