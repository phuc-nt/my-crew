// The unstick button cluster: Retry/Accept fire immediately, Drop/Cancel go through a
// confirm dialog first (destructive — lose a step's/task's in-flight work). Chịu lực:
// every button disables while ANY of the four mutations is pending (no double-fire);
// a failed mutation surfaces the backend's verbatim message via onError, not a canned
// string; the confirm dialog's own Cancel button dismisses without calling the API.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import type { TeamTaskActionResult } from '../../types'
import { LanguageProvider } from '../../i18n/language-context'
import { StalledTaskActions } from './stalled-task-actions'

function setup(onError?: (message: string) => void, showRecovery?: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <StalledTaskActions
          taskId="t1"
          stepId="s1"
          onError={onError}
          {...(showRecovery === undefined ? {} : { showRecovery })}
        />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('renders all four actions', () => {
  setup()
  expect(screen.getByRole('button', { name: 'Thử lại bước' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Chấp nhận kết quả hiện có' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Bỏ bước' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Hủy việc' })).toBeTruthy()
})

test('showRecovery=false hides Retry/Accept/Drop but keeps Cancel', () => {
  setup(undefined, false)
  expect(screen.queryByRole('button', { name: 'Thử lại bước' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Chấp nhận kết quả hiện có' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Bỏ bước' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Hủy việc' })).toBeTruthy()
})

test('retry fires immediately, no confirm dialog', async () => {
  const retry = vi.spyOn(api, 'retryStalledStep').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 't1', steps: [],
  })
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại bước' }))
  await waitFor(() => expect(retry).toHaveBeenCalledWith('t1', 's1'))
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('accept fires immediately, no confirm dialog', async () => {
  const accept = vi.spyOn(api, 'acceptStalledResult').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 't1', steps: [],
  })
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Chấp nhận kết quả hiện có' }))
  await waitFor(() => expect(accept).toHaveBeenCalledWith('t1', 's1'))
})

test('drop opens a confirm dialog and only calls the API after the second click', async () => {
  const drop = vi.spyOn(api, 'dropStalledStep').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 't1', steps: [],
  })
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Bỏ bước' }))
  expect(drop).not.toHaveBeenCalled()
  const dialog = await screen.findByRole('dialog', { name: 'Bỏ bước kẹt?' })
  fireEvent.click(
    within(dialog).getByRole('button', { name: 'Bỏ bước' }),
  )
  await waitFor(() => expect(drop).toHaveBeenCalledWith('t1', 's1'))
})

test('drop dialog cancel button dismisses without calling the API', async () => {
  const drop = vi.spyOn(api, 'dropStalledStep').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 't1', steps: [],
  })
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Bỏ bước' }))
  const dialog = await screen.findByRole('dialog', { name: 'Bỏ bước kẹt?' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hủy' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(drop).not.toHaveBeenCalled()
})

test('cancel opens a confirm dialog and only calls the API after the second click', async () => {
  const cancel = vi.spyOn(api, 'cancelTeamTask').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'cancelled', pic_id: '', room_id: 't1', steps: [],
  })
  setup()
  fireEvent.click(screen.getByRole('button', { name: 'Hủy việc' }))
  expect(cancel).not.toHaveBeenCalled()
  const dialog = await screen.findByRole('dialog', { name: 'Hủy việc này?' })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hủy việc' }))
  await waitFor(() => expect(cancel).toHaveBeenCalledWith('t1'))
})

test('buttons disable while a mutation is pending, guarding against a double-fire', async () => {
  let resolveRetry: (v: TeamTaskActionResult) => void = () => {}
  vi.spyOn(api, 'retryStalledStep').mockReturnValue(
    new Promise((resolve) => {
      resolveRetry = resolve
    }),
  )
  setup()
  const retryBtn = screen.getByRole('button', { name: 'Thử lại bước' })
  fireEvent.click(retryBtn)
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Đang thử lại…' }).hasAttribute('disabled')).toBe(
      true,
    ),
  )
  expect(
    screen.getByRole('button', { name: 'Chấp nhận kết quả hiện có' }).hasAttribute('disabled'),
  ).toBe(true)
  resolveRetry({ task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 't1', steps: [] })
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Thử lại bước' }).hasAttribute('disabled')).toBe(
      false,
    ),
  )
})

test('surfaces the backend verbatim error via onError, not a canned message', async () => {
  vi.spyOn(api, 'retryStalledStep').mockRejectedValue(
    new Error("việc `t1` không phải 'stalled'"),
  )
  const onError = vi.fn()
  setup(onError)
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại bước' }))
  await waitFor(() => expect(onError).toHaveBeenCalledWith("việc `t1` không phải 'stalled'"))
})

test('with roomId, a successful action invalidates the room artifacts (detail page repaint)', async () => {
  // Regression: the task-detail page renders from queryKeys.artifacts.room(roomId); a
  // stall action that invalidated only board + task.detail left that page frozen on the
  // pre-action 'stalled' state. Passing roomId must invalidate the room artifacts too.
  const { queryKeys } = await import('../../api/queries/query-keys')
  vi.spyOn(api, 'retryStalledStep').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 'room-xyz', steps: [],
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <StalledTaskActions taskId="t1" stepId="s1" roomId="room-xyz" />
      </LanguageProvider>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại bước' }))
  await waitFor(() =>
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.artifacts.room('room-xyz') }),
  )
})

test('without roomId (board card), no artifacts.room invalidation is attempted', async () => {
  vi.spyOn(api, 'retryStalledStep').mockResolvedValue({
    task_id: 't1', title: 'x', status: 'open', pic_id: '', room_id: 't1', steps: [],
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <StalledTaskActions taskId="t1" stepId="s1" />
      </LanguageProvider>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại bước' }))
  await waitFor(() => expect(invalidate).toHaveBeenCalled())
  const calls = invalidate.mock.calls.map((c) => JSON.stringify(c[0]))
  expect(calls.some((c) => c.includes('artifacts'))).toBe(false)
})
