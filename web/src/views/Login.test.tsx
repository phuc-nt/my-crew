// v6 M16 Login tests: submits credentials, calls onLoggedIn on success, surfaces the error
// on failure. Mocked api, no network (npm test).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Login } from './Login'

beforeEach(() => {
  vi.restoreAllMocks()
})

test('successful login calls onLoggedIn', async () => {
  vi.spyOn(api, 'login').mockResolvedValue({ ok: true })
  const onLoggedIn = vi.fn()
  render(<LanguageProvider><Login onLoggedIn={onLoggedIn} /></LanguageProvider>)
  fireEvent.change(screen.getByLabelText('Mật khẩu'), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))
  await waitFor(() => expect(onLoggedIn).toHaveBeenCalled())
  expect(api.login).toHaveBeenCalledWith('admin', 'pw')
})

test('wrong password shows the backend error', async () => {
  vi.spyOn(api, 'login').mockRejectedValue(new ApiError(401, 'Sai tên đăng nhập hoặc mật khẩu.'))
  render(<LanguageProvider><Login onLoggedIn={vi.fn()} /></LanguageProvider>)
  fireEvent.change(screen.getByLabelText('Mật khẩu'), { target: { value: 'bad' } })
  fireEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))
  await waitFor(() =>
    expect(screen.getByText(/Sai tên đăng nhập/)).toBeInTheDocument(),
  )
})

test('submit disabled with empty password', () => {
  render(<LanguageProvider><Login onLoggedIn={vi.fn()} /></LanguageProvider>)
  expect(screen.getByRole('button', { name: 'Đăng nhập' })).toBeDisabled()
})
