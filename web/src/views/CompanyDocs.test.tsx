// v7 M19 CompanyDocs library view: list, create, edit, delete. Mocked api, no network.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { CompanyDocs } from './CompanyDocs'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listCompanyDocs').mockResolvedValue({
    docs: [{ slug: 'leave', title: 'Nghỉ phép', updated: '2026-07-04', body: '12 ngày' }],
  })
})

test('lists docs and opens an editor with the body', async () => {
  render(<CompanyDocs />)
  fireEvent.click(await screen.findByText('Nghỉ phép'))
  expect(await screen.findByDisplayValue('12 ngày')).toBeInTheDocument()
})

test('creates a new doc', async () => {
  const create = vi
    .spyOn(api, 'createCompanyDoc')
    .mockResolvedValue({ slug: 'new', title: 'New', updated: '', body: 'B' })
  render(<CompanyDocs />)
  await screen.findByText('Nghỉ phép')
  fireEvent.click(screen.getByText('+ Tài liệu mới'))
  fireEvent.change(screen.getByPlaceholderText('Quy trình nghỉ phép'), {
    target: { value: 'Chính sách mới' },
  })
  fireEvent.click(screen.getByText('Lưu'))
  await waitFor(() => expect(create).toHaveBeenCalled())
  expect(create.mock.calls[0][0]).toBe('Chính sách mới')
})

test('deletes a doc after confirm', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const del = vi.spyOn(api, 'deleteCompanyDoc').mockResolvedValue({ ok: true })
  render(<CompanyDocs />)
  fireEvent.click(await screen.findByText('Nghỉ phép'))
  fireEvent.click(await screen.findByText('Xóa'))
  await waitFor(() => expect(del).toHaveBeenCalledWith('leave'))
})
