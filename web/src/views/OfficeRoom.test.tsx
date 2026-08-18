// Office group-chat room view (v12 M29): room picker (GET /api/office/rooms) + timeline
// rendering for all 5 event kinds. `useOfficeStream` is mocked (no real EventSource in
// jsdom, matching Trigger.test.tsx's convention of never exercising the real SSE hook).
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import * as officeStreamHook from '../hooks/use-office-stream'
import { AppProviders } from '../test-utils'
import type { OfficeMessage } from '../types'
import { OfficeRoom } from './OfficeRoom'

beforeEach(() => {
  vi.restoreAllMocks()
})

function wrap(initialPath = '/office') {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={[initialPath]}>
        <OfficeRoom />
      </MemoryRouter>
    </AppProviders>,
  )
}

function mockStream(messages: OfficeMessage[], extra: Partial<ReturnType<typeof officeStreamHook.useOfficeStream>> = {}) {
  vi.spyOn(officeStreamHook, 'useOfficeStream').mockReturnValue({
    messages,
    connected: true,
    errored: false,
    ...extra,
  })
}

test('renders the office overview room by default and lists other rooms as chips', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office', 't1', 't2'] })
  mockStream([])
  wrap()
  expect(await screen.findByText('Tổng quan')).toBeInTheDocument()
  expect(screen.getByText('Việc #t1')).toBeInTheDocument()
  expect(screen.getByText('Việc #t2')).toBeInTheDocument()
})

test('shows an empty-state message when the room has no activity yet', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([])
  wrap()
  await waitFor(() =>
    expect(screen.getByText('Chưa có hoạt động nào trong phòng này.')).toBeInTheDocument(),
  )
})

test('renders a ceo event with its Vietnamese label', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([
    { seq: 1, ts: 't', author: 'ceo', source_room_id: 't1', kind: 'ceo', body: { text: 'chuẩn bị demo' } },
  ])
  wrap()
  expect(await screen.findByText('CEO giao việc')).toBeInTheDocument()
  expect(screen.getByText('chuẩn bị demo')).toBeInTheDocument()
})

test('renders an assignment event', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([
    {
      seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'assignment',
      body: { task_title: 'Demo', step_count: 3, summary: 'Phân công: a, b' },
    },
  ])
  wrap()
  expect(await screen.findByText('Phân công')).toBeInTheDocument()
  expect(screen.getByText(/Demo — Phân công: a, b \(3 bước\)/)).toBeInTheDocument()
})

test('renders a step_status event', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([
    {
      seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'step_status',
      body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
    },
  ])
  wrap()
  expect(await screen.findByText('Tiến độ bước')).toBeInTheDocument()
  expect(screen.getByText(/Demo \/ draft: started/)).toBeInTheDocument()
})

test('renders a step_status event with a phase tag appended', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([
    {
      seq: 1, ts: 't', author: 'agent-a', source_room_id: 't1', kind: 'step_status',
      body: {
        task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a',
        phase: 'tu-soat', attempt_id: 'att-1',
      },
    },
  ])
  wrap()
  expect(await screen.findByText(/Demo \/ draft: started \(tự soát\)/)).toBeInTheDocument()
})

test('renders a handoff event', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([
    {
      seq: 1, ts: 't', author: 'agent-a', source_room_id: 't1', kind: 'handoff',
      body: { task_title: 'Demo', step_title: 'draft', message: 'đã xong bản nháp' },
    },
  ])
  wrap()
  expect(await screen.findByText('Bàn giao')).toBeInTheDocument()
  // v17: the handoff line is a fixed short notice — full result lives in the office
  // Kết quả column (artifact viewer), so the raw message no longer renders here.
  expect(screen.getByText(/đã bàn giao ✅/)).toBeInTheDocument()
})

test('renders a milestone event', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([
    {
      seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'milestone',
      body: { task_title: 'Demo', milestone: 'done', message: 'hoàn tất' },
    },
  ])
  wrap()
  expect(await screen.findByText('Cột mốc')).toBeInTheDocument()
  expect(screen.getByText(/Demo: hoàn tất/)).toBeInTheDocument()
})

test('shows a disconnected hint when the stream errors', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockResolvedValue({ rooms: ['office'] })
  mockStream([], { connected: false, errored: true })
  wrap()
  expect(await screen.findByText(/Mất kết nối luồng/)).toBeInTheDocument()
})

test('shows an error message when the room list fails to load', async () => {
  vi.spyOn(api, 'getOfficeRooms').mockRejectedValue(new Error('tải thất bại'))
  mockStream([])
  wrap()
  expect(await screen.findByText(/Lỗi: tải thất bại/)).toBeInTheDocument()
})
