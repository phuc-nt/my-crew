// v88 P5-B: "Sửa yêu cầu" at the preview phase — client-side only. Chịu lực: clicking it
// restores the originally submitted brief text to the draft, clears the preview (back to
// idle), and never calls the confirm endpoint (only the same best-effort cancel Cancel
// already uses for draft cleanup).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
import { AssignComposer } from './assign-composer'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAssignableStaff').mockResolvedValue({ web_search_ready: true, staff: [] })
})

test('editRequest restores the submitted brief, clears the preview, and calls no confirm', async () => {
  vi.spyOn(api, 'assignPreview').mockResolvedValue({
    preview_text: 'KẾ HOẠCH...', task_id: 't-1', plan_hash: 'h-1', pic_id: 'content',
    auto_confirmed: false, route_mode: '', pic_dry_run: false,
  })
  const cancel = vi.spyOn(api, 'assignCancel').mockResolvedValue({ ok: true })
  const confirm = vi.spyOn(api, 'assignConfirm')

  render(
    <AppProviders>
      <AssignComposer />
    </AppProviders>,
  )

  const input = await screen.findByPlaceholderText(/Giao việc/)
  fireEvent.change(input, { target: { value: '@content viết bài tuần này' } })
  fireEvent.keyDown(input, { key: 'Enter' })

  await screen.findByText('KẾ HOẠCH...')

  fireEvent.click(screen.getByRole('button', { name: 'Sửa yêu cầu' }))

  // Preview is gone (back to idle) and the original brief is back in the draft.
  await waitFor(() => expect(screen.queryByText('KẾ HOẠCH...')).not.toBeInTheDocument())
  expect(input).toHaveValue('@content viết bài tuần này')
  expect(cancel).toHaveBeenCalledWith('t-1')
  expect(confirm).not.toHaveBeenCalled()
})
