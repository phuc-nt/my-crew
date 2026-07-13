// v33 P3: outputs hub — renders step + file rows newest-first, step row opens the
// artifact viewer, file row is a confined download link, agent filter refetches.
// Kanban: lanes render with labels, card links to the workroom. Mocked api.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { Outputs } from './Outputs'
import { TeamTaskKanban } from './team-task-kanban'
import type { OutputsPayload, TeamBoardPayload } from '../types'

beforeEach(() => {
  vi.restoreAllMocks()
})

const outputs: OutputsPayload = {
  truncated: false,
  items: [
    {
      kind: 'step', task_id: 't1', task_title: 'Việc A', room_id: 't1',
      seq: 1, step_title: 'Soạn nội dung', agent_id: 'noi-dung',
      ts: '2026-07-13T01:00:00+00:00',
    },
    {
      kind: 'file', task_id: '', task_title: '', room_id: '', seq: 0,
      step_title: '', agent_id: 'phan-tich', ts: '2026-07-12T01:00:00+00:00',
      name: 'bao-cao.xlsx', size: 123,
    },
  ],
}

function renderOutputs() {
  return render(
    <MemoryRouter>
      <Outputs />
    </MemoryRouter>,
  )
}

test('renders step and file rows; file is a confined download link', async () => {
  vi.spyOn(api, 'getOutputs').mockResolvedValue(outputs)
  renderOutputs()

  expect(await screen.findByText('Soạn nội dung')).toBeInTheDocument()
  const fileLink = screen.getByText(/bao-cao\.xlsx/).closest('a')
  expect(fileLink).toHaveAttribute('href', '/api/outputs/file/phan-tich/bao-cao.xlsx')
})

test('step row opens the artifact viewer with the step content', async () => {
  vi.spyOn(api, 'getOutputs').mockResolvedValue(outputs)
  vi.spyOn(api, 'getStepArtifact').mockResolvedValue({
    task_id: 't1', step_title: 'Soạn nội dung',
    result_text: '## Bản nháp cuối', attempt: 'a1', self_check_failed: false,
  })
  renderOutputs()

  fireEvent.click(await screen.findByText('Soạn nội dung'))
  expect(await screen.findByText('Bản nháp cuối')).toBeInTheDocument()
})

test('agent filter refetches with the chosen agent', async () => {
  const get = vi.spyOn(api, 'getOutputs').mockResolvedValue(outputs)
  renderOutputs()
  await screen.findByText('Soạn nội dung')

  fireEvent.change(screen.getByDisplayValue('tất cả'), { target: { value: 'noi-dung' } })
  await waitFor(() => expect(get).toHaveBeenLastCalledWith('noi-dung', undefined))
})

const board: TeamBoardPayload = {
  lanes: [
    { id: 'planning', cards: [] },
    {
      id: 'running',
      cards: [{
        task_id: 't9', title: 'Soạn kế hoạch quý', pic_id: 'truong-phong',
        room_id: 'room-9', status: 'running', created_at: '2026-07-13',
        steps_done: 1, steps_total: 3,
      }],
    },
    { id: 'done', cards: [] },
    { id: 'khac', cards: [] },
  ],
}

test('kanban renders non-empty lanes and links cards to their workroom', async () => {
  vi.spyOn(api, 'getTeamTaskBoard').mockResolvedValue(board)
  render(
    <MemoryRouter>
      <TeamTaskKanban />
    </MemoryRouter>,
  )

  expect(await screen.findByText('Đang chạy (1)')).toBeInTheDocument()
  expect(screen.queryByText(/Chờ xác nhận/)).not.toBeInTheDocument()
  const card = screen.getByText('Soạn kế hoạch quý').closest('a')
  expect(card).toHaveAttribute('href', '/office?room=room-9')
  expect(screen.getByText('1/3 bước')).toBeInTheDocument()
})

test('kanban renders nothing when the board is empty', async () => {
  vi.spyOn(api, 'getTeamTaskBoard').mockResolvedValue({ lanes: [] })
  const { container } = render(
    <MemoryRouter>
      <TeamTaskKanban />
    </MemoryRouter>,
  )
  await waitFor(() => expect(api.getTeamTaskBoard).toHaveBeenCalled())
  expect(container.querySelector('.team-kanban')).toBeNull()
})
