// staff-template-picker (v32): one-click create per card (confirm → createFromTemplate),
// "Tuỳ chỉnh…" keeps the old prefill path, crew banner previews then creates the crew,
// and every failure path keeps the manual wizard reachable.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
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
  academic_search: false,
  schedule: {},
  has_skills: false,
}

const CREW = {
  crew_id: 'office',
  crew: 'Đội văn phòng mẫu',
  members: [
    { role_id: 'truong-phong', role: 'Trưởng phòng', domain: 'office', exists: false },
    { role_id: 'noi-dung', role: 'Nội dung', domain: 'office', exists: true },
  ],
  coordinator: 'truong-phong',
  coordinator_already_set: false,
  current_coordinator: null,
}

const PERSONAL_CREW = {
  crew_id: 'personal',
  crew: 'Đội cá nhân',
  members: [
    { role_id: 'coordinator', role: 'Điều phối', domain: 'pm', exists: true },
    { role_id: 'pong', role: 'Trợ lý cá nhân', domain: 'personal', exists: false },
  ],
  coordinator: 'coordinator',
  coordinator_already_set: false,
  current_coordinator: null,
}

function renderPicker(onApply = vi.fn(), onSkip = vi.fn()) {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <StaffTemplatePicker onApply={onApply} onSkip={onSkip} />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getCrewPreview').mockResolvedValue(CREW)
})

test('quick create: card confirm → createFromTemplate with only the role_id', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [PM_PACK] })
  const create = vi.spyOn(api, 'createFromTemplate').mockResolvedValue({
    id: 'pm-coordinator', domain: 'pm', reports: ['daily'],
    name: 'Điều phối dự án', hint: 'Điền token.',
  })
  renderPicker()
  await waitFor(() => expect(screen.getByText('Điều phối dự án')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Tạo ngay'))
  fireEvent.click(screen.getByText('Xác nhận'))
  await waitFor(() => expect(create).toHaveBeenCalledWith('pm-coordinator'))
  await waitFor(() => expect(screen.getByText(/Đã tạo "pm-coordinator"/)).toBeInTheDocument())
})

test('customize keeps the old prefill path (onApply with resolved pack)', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [PM_PACK] })
  const onApply = vi.fn()
  renderPicker(onApply)
  await waitFor(() => expect(screen.getByText('Điều phối dự án')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Tuỳ chỉnh…'))
  expect(onApply).toHaveBeenCalledWith(PM_TEMPLATE, PM_PACK)
})

test('crew banner: preview lists members (existing marked), confirm creates', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [PM_PACK] })
  const create = vi.spyOn(api, 'createCrew').mockResolvedValue({
    crew_id: 'office', crew: 'Đội văn phòng mẫu', created: ['truong-phong'],
    skipped: ['noi-dung'], failed: [], coordinator_id: 'truong-phong',
  })
  renderPicker()
  await waitFor(() => expect(screen.getByText(/Tạo cả đội \(1\)/)).toBeInTheDocument())

  fireEvent.click(screen.getByText(/Tạo cả đội \(1\)/))
  expect(screen.getByText(/đã có, bỏ qua/)).toBeInTheDocument()
  fireEvent.click(screen.getByText(/Xác nhận tạo 1 nhân sự/))
  // The previewed crew is the one created — not a hardcoded server default.
  await waitFor(() => expect(create).toHaveBeenCalledWith('office'))
  await waitFor(() => expect(screen.getByText(/Đã tạo 1 nhân sự/)).toBeInTheDocument())
  expect(screen.getByText(/trưởng phòng: truong-phong/)).toBeInTheDocument()
})

test('crew picker: switching crew re-previews and creates THAT crew', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [PM_PACK] })
  vi.spyOn(api, 'getCrews').mockResolvedValue({
    crews: [
      { id: 'office', name: 'Đội văn phòng mẫu', member_count: 2 },
      { id: 'personal', name: 'Đội cá nhân', member_count: 2 },
    ],
    default: 'office',
  })
  const preview = vi.spyOn(api, 'getCrewPreview')
  preview.mockResolvedValueOnce(CREW).mockResolvedValueOnce(PERSONAL_CREW)
  const create = vi.spyOn(api, 'createCrew').mockResolvedValue({
    crew_id: 'personal', crew: 'Đội cá nhân', created: ['pong'], skipped: ['coordinator'],
    failed: [], coordinator_id: 'coordinator',
  })
  renderPicker()
  await waitFor(() => expect(screen.getByText('Đội cá nhân')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Đội cá nhân'))
  await waitFor(() => expect(preview).toHaveBeenCalledWith('personal'))
  await waitFor(() => expect(screen.getByText(/Tạo cả đội \(1\)/)).toBeInTheDocument())

  fireEvent.click(screen.getByText(/Tạo cả đội \(1\)/))
  await waitFor(() => expect(screen.getByText(/Trợ lý cá nhân/)).toBeInTheDocument())
  fireEvent.click(screen.getByText(/Xác nhận tạo 1 nhân sự/))
  await waitFor(() => expect(create).toHaveBeenCalledWith('personal'))
})

test('a fetch failure keeps the manual path reachable, no dead-end', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockRejectedValue(new Error('mạng lỗi'))
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [] })
  const onSkip = vi.fn()
  renderPicker(vi.fn(), onSkip)
  await waitFor(() => expect(screen.getByText(/mạng lỗi/)).toBeInTheDocument())

  fireEvent.click(screen.getByText('Bỏ qua, tự chọn'))
  expect(onSkip).toHaveBeenCalled()
})

test('missing pack for a template shows inline error instead of navigating', async () => {
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [PM_TEMPLATE] })
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [] })
  const onApply = vi.fn()
  renderPicker(onApply)
  await waitFor(() => expect(screen.getByText('Điều phối dự án')).toBeInTheDocument())

  fireEvent.click(screen.getByText('Tuỳ chỉnh…'))
  expect(onApply).not.toHaveBeenCalled()
  expect(screen.getByText(/chưa cài/)).toBeInTheDocument()
})
