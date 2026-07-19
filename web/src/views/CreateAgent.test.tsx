// CreateAgent wizard: happy path builds the correct POST body (incl. schedule cron), and
// a 400/409 from the backend surfaces the exact `detail` string inline. Mocked api (no
// network), matching the rest of the SPA's test style.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { CreateAgent } from './CreateAgent'

const PM_PACK = {
  id: 'pm',
  name: 'Project Management',
  report_kinds: ['daily', 'weekly'],
  servers: ['slack', 'jira'],
}

const HR_PACK = {
  id: 'hr',
  name: 'Human Resources',
  report_kinds: ['headcount'],
  servers: ['slack'],
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getPacks').mockResolvedValue({ packs: [PM_PACK, HR_PACK] })
  vi.spyOn(api, 'getStaffTemplates').mockResolvedValue({ templates: [] })
})

function wrap(ui: React.ReactElement) {
  return render(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  )
}

// Step 0 is the optional staff-template picker — these tests exercise the manual path,
// so skip it every time.
async function skipTemplateStep() {
  await waitFor(() => expect(screen.getByText('Bỏ qua, tự chọn')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Bỏ qua, tự chọn'))
  await waitFor(() => expect(screen.getByText('Project Management')).toBeInTheDocument())
}

async function goToReview() {
  wrap(<CreateAgent />)
  await skipTemplateStep()

  // Step 1: pick the pack
  fireEvent.click(screen.getByRole('radio', { name: /Project Management/ }))
  fireEvent.click(screen.getByText('Tiếp'))

  // Step 2: identity
  fireEvent.change(screen.getByPlaceholderText('sales-pm'), { target: { value: 'acme-pm' } })
  fireEvent.change(screen.getByPlaceholderText('PM Kinh doanh'), { target: { value: 'Acme PM' } })
  fireEvent.click(screen.getByText('Tiếp'))

  // Step 3: reports + schedule
  fireEvent.click(screen.getByLabelText('Báo cáo hằng ngày'))
  fireEvent.click(screen.getByLabelText('T2'))
  fireEvent.click(screen.getByText('Tiếp'))

  // Step 4: bindings (skip)
  fireEvent.click(screen.getByText('Tiếp'))
}

test('happy path builds the correct POST body including cron schedule', async () => {
  const createAgent = vi.spyOn(api, 'createAgent').mockResolvedValue({
    created: { id: 'acme-pm', domain: 'pm', reports: ['daily'] },
  })
  await goToReview()

  fireEvent.click(screen.getByRole('button', { name: 'Tạo agent' }))
  await waitFor(() => expect(createAgent).toHaveBeenCalled())
  const spec = createAgent.mock.calls[0][0]
  expect(spec.id).toBe('acme-pm')
  expect(spec.name).toBe('Acme PM')
  expect(spec.domain).toBe('pm')
  expect(spec.reports).toEqual(['daily'])
  expect(spec.schedule).toEqual({ daily: '0 9 * * 1' })

  await waitFor(() => expect(screen.getByText(/Đã tạo agent/)).toBeInTheDocument())
})

test('400 detail from the backend surfaces inline', async () => {
  vi.spyOn(api, 'createAgent').mockRejectedValue(
    new ApiError(400, "report kind(s) ['bogus'] not served by the 'pm' pack"),
  )
  await goToReview()

  fireEvent.click(screen.getByRole('button', { name: 'Tạo agent' }))
  await waitFor(() =>
    expect(screen.getByText(/not served by the 'pm' pack/)).toBeInTheDocument(),
  )
})

test('switching packs after selecting reports does not leak the stale report kind into Create', async () => {
  const createAgent = vi.spyOn(api, 'createAgent').mockResolvedValue({
    created: { id: 'acme-hr', domain: 'hr', reports: ['headcount'] },
  })
  wrap(<CreateAgent />)
  await skipTemplateStep()

  // Step 1: pick pm, select "daily" in step 3, then go Back to step 1 and pick hr instead.
  fireEvent.click(screen.getByRole('radio', { name: /Project Management/ }))
  fireEvent.click(screen.getByText('Tiếp')) // -> step 2
  fireEvent.change(screen.getByPlaceholderText('sales-pm'), { target: { value: 'acme-hr' } })
  fireEvent.change(screen.getByPlaceholderText('PM Kinh doanh'), { target: { value: 'Acme HR' } })
  fireEvent.click(screen.getByText('Tiếp')) // -> step 3
  fireEvent.click(screen.getByLabelText('Báo cáo hằng ngày'))
  fireEvent.click(screen.getByText('Quay lại')) // -> step 2
  fireEvent.click(screen.getByText('Quay lại')) // -> step 1
  await waitFor(() => expect(screen.getByText('Human Resources')).toBeInTheDocument())

  fireEvent.click(screen.getByRole('radio', { name: /Human Resources/ }))
  fireEvent.click(screen.getByText('Tiếp')) // -> step 2 (id/name preserved)
  expect(screen.getByPlaceholderText('sales-pm')).toHaveValue('acme-hr')
  fireEvent.click(screen.getByText('Tiếp')) // -> step 3: only hr's kinds render
  expect(screen.queryByLabelText('Báo cáo hằng ngày')).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('headcount'))
  fireEvent.click(screen.getByText('Tiếp')) // -> step 4
  fireEvent.click(screen.getByText('Tiếp')) // -> step 5

  fireEvent.click(screen.getByRole('button', { name: 'Tạo agent' }))
  await waitFor(() => expect(createAgent).toHaveBeenCalled())
  const spec = createAgent.mock.calls[0][0]
  expect(spec.domain).toBe('hr')
  expect(spec.reports).toEqual(['headcount'])
})
