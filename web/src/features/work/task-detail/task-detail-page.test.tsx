// The task detail page's unstick panel: a stalled task shows its reason + the four
// actions right where the CEO is already looking (no chat detour); a live (open/
// running) task still offers Cancel, since "hủy task" is a control worth having on a
// task that hasn't stalled too. A done/cancelled task shows neither.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../../api/client'
import { LanguageProvider } from '../../../i18n/language-context'
import type { RoomArtifactsPayload } from '../../../types'
import { TaskDetailPage } from './task-detail-page'

function taskPayload(over: Partial<RoomArtifactsPayload['tasks'][number]> = {}): RoomArtifactsPayload {
  return {
    tasks: [
      {
        task_id: 't1',
        title: 'Soạn báo cáo tuần',
        pic_id: 'analyst',
        status: 'stalled',
        steps: [
          { step_id: 's1', title: 'thu thập số liệu', assigned_to: 'analyst',
            status: 'failed', seq: 1, step_type: 'work' },
        ],
        ...over,
      },
    ],
  }
}

function setup(room = 'room-1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <MemoryRouter initialEntries={[`/work/task/${room}`]}>
          <Routes>
            <Route path="/work/task/:room" element={<TaskDetailPage />} />
          </Routes>
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('a stalled task shows the stalled reason and the four unstick actions', async () => {
  vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue(taskPayload())
  vi.spyOn(api, 'getTeamTaskRoute').mockResolvedValue({ task_id: 't1', mode: '', source: '', reason: '' })
  vi.spyOn(api, 'getTeamTaskMetrics').mockResolvedValue({ task_id: 't1', mode: '', status: 'stalled', wall_clock_seconds: null, wall_clock_text: '', cost_usd: 0, step_count: 0, content_steps: 0, review_steps: 0, rework_steps: 0, steps: [] })
  setup()

  await screen.findByText('Kẹt ở bước "thu thập số liệu"')
  expect(screen.getByRole('button', { name: 'Thử lại bước' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Chấp nhận kết quả hiện có' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Bỏ bước' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Hủy việc' })).toBeTruthy()
})

test('a review-exhausted stall (no dead step) shows the fallback reason line', async () => {
  vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue(
    taskPayload({
      steps: [
        { step_id: 's1', title: 'draft', assigned_to: 'analyst', status: 'done',
          seq: 1, step_type: 'work' },
      ],
    }),
  )
  vi.spyOn(api, 'getTeamTaskRoute').mockResolvedValue({ task_id: 't1', mode: '', source: '', reason: '' })
  vi.spyOn(api, 'getTeamTaskMetrics').mockResolvedValue({ task_id: 't1', mode: '', status: 'stalled', wall_clock_seconds: null, wall_clock_text: '', cost_usd: 0, step_count: 0, content_steps: 0, review_steps: 0, rework_steps: 0, steps: [] })
  setup()

  await screen.findByText('Kẹt vì đã hết lượt duyệt lại — chọn một hành động bên dưới.')
})

test('a live (open) task offers Cancel but not the stalled-only reason line', async () => {
  vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue(
    taskPayload({ status: 'open', steps: [] }),
  )
  vi.spyOn(api, 'getTeamTaskRoute').mockResolvedValue({ task_id: 't1', mode: '', source: '', reason: '' })
  vi.spyOn(api, 'getTeamTaskMetrics').mockResolvedValue({ task_id: 't1', mode: '', status: 'stalled', wall_clock_seconds: null, wall_clock_text: '', cost_usd: 0, step_count: 0, content_steps: 0, review_steps: 0, rework_steps: 0, steps: [] })
  setup()

  await waitFor(() => expect(screen.getByRole('button', { name: 'Hủy việc' })).toBeTruthy())
  expect(screen.queryByText(/^Kẹt/)).toBeNull()
  // Retry/Accept/Drop hit the ops layer's "not stalled" guard on a healthy task —
  // they're recovery actions, hidden until the task is actually stalled.
  expect(screen.queryByRole('button', { name: 'Thử lại bước' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Chấp nhận kết quả hiện có' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Bỏ bước' })).toBeNull()
})

test('a done task shows neither the panel nor the unstick actions', async () => {
  vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue(
    taskPayload({ status: 'done', steps: [] }),
  )
  vi.spyOn(api, 'getTeamTaskRoute').mockResolvedValue({ task_id: 't1', mode: '', source: '', reason: '' })
  vi.spyOn(api, 'getTeamTaskMetrics').mockResolvedValue({ task_id: 't1', mode: '', status: 'stalled', wall_clock_seconds: null, wall_clock_text: '', cost_usd: 0, step_count: 0, content_steps: 0, review_steps: 0, rework_steps: 0, steps: [] })
  setup()

  await screen.findByText('Soạn báo cáo tuần')
  expect(screen.queryByRole('button', { name: 'Hủy việc' })).toBeNull()
})
