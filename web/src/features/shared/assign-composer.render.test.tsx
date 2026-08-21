// v87 P2: the composer's preview-time dry-run badge — proves `pic_dry_run: true` from
// the preview payload renders the "diễn tập" warning BEFORE the CEO confirms, and that
// a live PIC (pic_dry_run: false) shows no badge at all.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
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
