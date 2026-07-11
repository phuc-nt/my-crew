// staff-template-picker: fetches templates + packs, resolves a chosen template's domain
// to the matching Pack, and calls onApply(template, pack) — or onSkip() to bypass.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { StaffTemplatePicker } from './staff-template-picker'

const PM_PACK = { id: 'pm', name: 'Project Management', report_kinds: ['daily', 'weekly'], servers: ['jira'] }

const PM_TEMPLATE = {
  role_id: 'pm-coordinator',
  role: 'Điều phối dự án',
  domain: 'pm',
  reports: ['daily'],
  bindings_hint: ['jira'],
  persona: '# SOUL',
  web_search: false,
  recommended_runtime: 'native',
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('renders a template card and calls onApply with the resolved pack', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [PM_PACK] })
  const onApply = vi.fn()

  render(<StaffTemplatePicker onApply={onApply} onSkip={vi.fn()} />)
  await waitFor(() => expect(screen.getByText('Điều phối dự án')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Dùng mẫu này'))
  expect(onApply).toHaveBeenCalledWith(PM_TEMPLATE, PM_PACK)
})

test('onSkip fires without fetching anything blocking', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [] })
  const onSkip = vi.fn()

  render(<StaffTemplatePicker onApply={vi.fn()} onSkip={onSkip} />)
  await waitFor(() => expect(screen.getByText('Bỏ qua, tự chọn')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Bỏ qua, tự chọn'))
  expect(onSkip).toHaveBeenCalled()
})

test('shows an inline error when the template domain has no installed pack', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [] }) // pm not installed
  const onApply = vi.fn()

  render(<StaffTemplatePicker onApply={onApply} onSkip={vi.fn()} />)
  await waitFor(() => expect(screen.getByText('Điều phối dự án')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Dùng mẫu này'))
  expect(onApply).not.toHaveBeenCalled()
  expect(screen.getByText(/chưa cài/)).toBeInTheDocument()
})

test('a fetch failure keeps "Bỏ qua, tự chọn" reachable, no dead-end (red-team M4)', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockRejectedValue(new Error('mạng lỗi'))
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [] })
  const onSkip = vi.fn()

  render(<StaffTemplatePicker onApply={vi.fn()} onSkip={onSkip} />)
  await waitFor(() => expect(screen.getByText(/mạng lỗi/)).toBeInTheDocument())

  fireEvent.click(screen.getByText('Bỏ qua, tự chọn'))
  expect(onSkip).toHaveBeenCalled()
})
