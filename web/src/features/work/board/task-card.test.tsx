// Nút bỏ bản nháp. Bản nháp (kế hoạch đã xem trước, chưa xác nhận) nằm cùng bảng và nhìn
// y hệt việc thật — trước đây không có đường bỏ nó đi từ bảng.
//
// Chịu lực: nút CHỈ hiện ở cột lập kế hoạch (bấm nhầm trên việc đang chạy là mất việc);
// bấm nút không mở trang việc (nút nằm ngoài <Link> bọc thẻ); bấm xong bảng nạp lại từ
// backend chứ không tự xoá thẻ lạc quan.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../../api/client'
import { LanguageProvider } from '../../../i18n/language-context'
import type { TeamBoardCard } from '../../../types'
import { TaskCard } from './task-card'

const CARD: TeamBoardCard = {
  task_id: 'tsk-1',
  title: 'Soạn báo cáo tuần',
  pic_id: 'analyst',
  room_id: 'room-1',
  status: 'planning',
  created_at: '2026-08-19T09:00:00Z',
  steps_done: 0,
  steps_total: 0,
}

function setup(lane: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  const view = render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <MemoryRouter>
          <TaskCard card={CARD} lane={lane} />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidate }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('offers the dismiss button only on the planning lane', () => {
  setup('planning')
  expect(screen.getByRole('button', { name: 'Hủy nháp' })).toBeTruthy()
})

test.each(['open', 'running', 'done', 'khac'])(
  'never offers dismiss on the %s lane — a real task must not be discardable',
  (lane) => {
    setup(lane)
    expect(screen.queryByRole('button', { name: 'Hủy nháp' })).toBeNull()
  },
)

test('cancels the draft by task id and refetches the board', async () => {
  const cancel = vi.spyOn(api, 'assignCancel').mockResolvedValue({ ok: true })
  const { invalidate } = setup('planning')
  fireEvent.click(screen.getByRole('button', { name: 'Hủy nháp' }))
  await waitFor(() => expect(cancel).toHaveBeenCalledWith('tsk-1'))
  // Bảng vẽ lại từ backend — nếu điều phối viên vừa kịp xác nhận nháp thì thẻ vẫn còn.
  await waitFor(() => expect(invalidate).toHaveBeenCalled())
})

test('still refetches when the cancel call fails, so the board never lies', async () => {
  vi.spyOn(api, 'assignCancel').mockRejectedValue(new Error('boom'))
  const { invalidate } = setup('planning')
  fireEvent.click(screen.getByRole('button', { name: 'Hủy nháp' }))
  await waitFor(() => expect(invalidate).toHaveBeenCalled())
  // Nút mở lại được: thất bại không khoá thẻ vĩnh viễn.
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Hủy nháp' }).hasAttribute('disabled')).toBe(false),
  )
})
