// v88 P5-A: `initialBrief` pre-fills the composer's draft on mount (the task-detail
// page's "Giao lại việc này" hands the old task's brief + PIC mention over this way).
// Chịu lực: the seed lands in the input with no network call — seeding is local state,
// not a submit.
import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { AppProviders } from '../../test-utils'
import { AssignComposer } from './assign-composer'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAssignableStaff').mockResolvedValue({ web_search_ready: true, staff: [] })
})

test('initialBrief pre-fills the draft on mount without calling any assign endpoint', async () => {
  const preview = vi.spyOn(api, 'assignPreview')
  const roomChat = vi.spyOn(api, 'roomChat')
  render(
    <AppProviders>
      <AssignComposer initialBrief="@analyst Soạn báo cáo tuần" />
    </AppProviders>,
  )

  const input = await screen.findByPlaceholderText(/Giao việc/)
  expect(input).toHaveValue('@analyst Soạn báo cáo tuần')
  expect(preview).not.toHaveBeenCalled()
  expect(roomChat).not.toHaveBeenCalled()
})

test('an absent initialBrief leaves the composer empty as before', async () => {
  render(
    <AppProviders>
      <AssignComposer />
    </AppProviders>,
  )

  const input = await screen.findByPlaceholderText(/Giao việc/)
  expect(input).toHaveValue('')
})
