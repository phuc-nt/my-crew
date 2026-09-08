// v87 P2: the composer's preview-time dry-run badge — proves `pic_dry_run: true` from
// the preview payload renders the "diễn tập" warning BEFORE the CEO confirms, and that
// a live PIC (pic_dry_run: false) shows no badge at all.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
import type { RoomChatPayload } from '../../types'
import { AssignComposer } from './assign-composer'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAssignableStaff').mockResolvedValue({ web_search_ready: true, staff: [] })
})

function wrap() {
  return render(
    <AppProviders>
      <AssignComposer />
    </AppProviders>,
  )
}

test('preview shows the dry-run badge when the previewed PIC would not send for real', async () => {
  vi.spyOn(api, 'assignPreview').mockResolvedValue({
    preview_text: 'KẾ HOẠCH...', task_id: 't-1', plan_hash: 'h-1', pic_id: 'content',
    auto_confirmed: false, route_mode: '', pic_dry_run: true,
  })
  wrap()
  fireEvent.change(screen.getByPlaceholderText(/Giao việc/), {
    target: { value: '@content viết bài' },
  })
  fireEvent.keyDown(screen.getByPlaceholderText(/Giao việc/), { key: 'Enter' })

  await waitFor(() => expect(screen.getByText(/DIỄN TẬP/)).toBeInTheDocument())
})

test('preview shows no dry-run badge when the previewed PIC sends for real', async () => {
  vi.spyOn(api, 'assignPreview').mockResolvedValue({
    preview_text: 'KẾ HOẠCH...', task_id: 't-2', plan_hash: 'h-2', pic_id: 'content',
    auto_confirmed: false, route_mode: '', pic_dry_run: false,
  })
  wrap()
  fireEvent.change(screen.getByPlaceholderText(/Giao việc/), {
    target: { value: '@content viết bài' },
  })
  fireEvent.keyDown(screen.getByPlaceholderText(/Giao việc/), { key: 'Enter' })

  await waitFor(() => expect(screen.getByText('KẾ HOẠCH...')).toBeInTheDocument())
  expect(screen.queryByText(/DIỄN TẬP/)).not.toBeInTheDocument()
})

// Pre-authorization: the scope the CEO picks on the card is the third argument of the
// confirm call, and a manifest with no gate never sends one.
test('the scope picked on the preauth card travels with confirm', async () => {
  vi.spyOn(api, 'assignPreview').mockResolvedValue({
    preview_text: 'KẾ HOẠCH...', task_id: 't-3', plan_hash: 'h-3', pic_id: 'assistant',
    auto_confirmed: false, route_mode: '', pic_dry_run: false,
    manifest: {
      external_count: 1,
      steps: [{
        step_id: 's1', title: 'gửi email khách', assigned_to: 'assistant',
        external_write: true, needs_shell: false, needs_web: false, needs_mail: true, needs_review: false,
      }],
    },
  })
  const confirm = vi.spyOn(api, 'assignConfirm').mockResolvedValue({ text: 'Đã giao.', preauth_scope: 'always' })
  wrap()
  fireEvent.change(screen.getByPlaceholderText(/Giao việc/), { target: { value: 'gửi mail' } })
  fireEvent.keyDown(screen.getByPlaceholderText(/Giao việc/), { key: 'Enter' })
  await waitFor(() => expect(screen.getByTestId('preauth-scope')).toBeInTheDocument())
  fireEvent.click(screen.getByLabelText(/ghi thành luật/))
  fireEvent.click(screen.getByText('Xác nhận giao việc'))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith('t-3', 'h-3', 'always'))
})

test('a plan with no gate confirms with an empty scope', async () => {
  vi.spyOn(api, 'assignPreview').mockResolvedValue({
    preview_text: 'KẾ HOẠCH...', task_id: 't-4', plan_hash: 'h-4', pic_id: 'content',
    auto_confirmed: false, route_mode: '', pic_dry_run: false,
    manifest: { external_count: 0, steps: [] },
  })
  const confirm = vi.spyOn(api, 'assignConfirm').mockResolvedValue({ text: 'Đã giao.' })
  wrap()
  fireEvent.change(screen.getByPlaceholderText(/Giao việc/), { target: { value: 'viết bài' } })
  fireEvent.keyDown(screen.getByPlaceholderText(/Giao việc/), { key: 'Enter' })
  await waitFor(() => expect(screen.getByTestId('preauth-card')).toBeInTheDocument())
  expect(screen.queryByTestId('preauth-scope')).toBeNull()
  fireEvent.click(screen.getByText('Xác nhận giao việc'))
  await waitFor(() => expect(confirm).toHaveBeenCalledWith('t-4', 'h-4', ''))
})

// Queued follow-ups: text typed while a round-trip is in flight is parked, shown as a
// chip, and sent on its own once the composer is free — but never over a live preview.
test('a follow-up typed mid-flight is queued and flushed after the reply', async () => {
  let release: (v: RoomChatPayload) => void = () => {}
  const roomChat = vi.spyOn(api, 'roomChat').mockImplementationOnce(
    () => new Promise((r) => { release = r }),
  ).mockResolvedValueOnce({ intent: 'question', reply: 'Trả lời 2' })
  render(
    <AppProviders>
      <AssignComposer activeRoom="room-1" />
    </AppProviders>,
  )
  const box = screen.getByPlaceholderText(/Chat trong phòng việc/)
  fireEvent.change(box, { target: { value: 'câu 1' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  await waitFor(() => expect(roomChat).toHaveBeenCalledTimes(1))
  fireEvent.change(box, { target: { value: 'câu 2' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  expect(screen.getByText('câu 2', { selector: '.office-composer-queued span' })).toBeInTheDocument()
  expect(roomChat).toHaveBeenCalledTimes(1)
  release({ intent: 'question', reply: 'Trả lời 1' })
  await waitFor(() => expect(roomChat).toHaveBeenLastCalledWith('room-1', 'câu 2'))
  await waitFor(() => expect(screen.queryByText('câu 2', { selector: '.office-composer-queued span' })).toBeNull())
})

test('a queued follow-up waits behind a live preview', async () => {
  let release: (v: RoomChatPayload) => void = () => {}
  const roomChat = vi.spyOn(api, 'roomChat').mockImplementationOnce(
    () => new Promise((r) => { release = r }),
  )
  render(
    <AppProviders>
      <AssignComposer activeRoom="room-1" />
    </AppProviders>,
  )
  const box = screen.getByPlaceholderText(/Chat trong phòng việc/)
  fireEvent.change(box, { target: { value: 'việc mới' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  await waitFor(() => expect(roomChat).toHaveBeenCalledTimes(1))
  fireEvent.change(box, { target: { value: 'thêm nữa' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  release({
    intent: 'new_task', preview_text: 'KẾ HOẠCH', task_id: 't-9', plan_hash: 'h-9', pic_id: 'content',
  })
  await waitFor(() => expect(screen.getByText('Xác nhận giao việc')).toBeInTheDocument())
  expect(roomChat).toHaveBeenCalledTimes(1)
  expect(screen.getByText('thêm nữa', { selector: '.office-composer-queued span' })).toBeInTheDocument()
})
