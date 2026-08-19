// Ô đổi mật khẩu. Chịu lực: giấu hẳn khi chưa bật đăng nhập; chặn ngay khi hai ô mật khẩu
// mới lệch nhau (gõ nhầm rồi bị đá ra là mất đường vào); gửi đúng cặp mật khẩu lên backend;
// đổi xong hiện lời nhắc đăng nhập lại thay vì im lặng.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import { ChangePasswordBox } from './change-password-box'

function renderBox() {
  return render(
    <LanguageProvider>
      <ChangePasswordBox />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('hides itself entirely when login is not enabled', async () => {
  vi.spyOn(api, 'getMe').mockResolvedValue({ authenticated: true, auth: 'disabled' })
  const { container } = renderBox()
  // Không có mật khẩu nào để đổi — bày ra một nút chỉ để báo lỗi thì tệ hơn là giấu.
  await waitFor(() => expect(container).toBeEmptyDOMElement())
})

test('sends the current and new password when the two new fields match', async () => {
  vi.spyOn(api, 'getMe').mockResolvedValue({ authenticated: true, user: 'ceo' })
  const change = vi
    .spyOn(api, 'changePassword')
    .mockResolvedValue({ ok: true, restarting: true, message: 'Đã đổi mật khẩu.' })
  renderBox()
  await screen.findByText('Đổi mật khẩu đăng nhập')
  fireEvent.change(screen.getByLabelText('Mật khẩu hiện tại'), { target: { value: 'oldpass' } })
  fireEvent.change(screen.getByLabelText('Mật khẩu mới'), { target: { value: 'brandnew' } })
  fireEvent.change(screen.getByLabelText('Nhập lại mật khẩu mới'), { target: { value: 'brandnew' } })
  fireEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
  await waitFor(() => expect(change).toHaveBeenCalledWith('oldpass', 'brandnew'))
  // Đổi xong phải nói rõ phải đăng nhập lại, không im lặng như một lần lưu cài đặt.
  expect(await screen.findByText('Đã đổi mật khẩu.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Về màn đăng nhập' })).toBeTruthy()
})

test('refuses locally when the two new-password fields differ', async () => {
  vi.spyOn(api, 'getMe').mockResolvedValue({ authenticated: true, user: 'ceo' })
  const change = vi.spyOn(api, 'changePassword')
  renderBox()
  await screen.findByText('Đổi mật khẩu đăng nhập')
  fireEvent.change(screen.getByLabelText('Mật khẩu hiện tại'), { target: { value: 'oldpass' } })
  fireEvent.change(screen.getByLabelText('Mật khẩu mới'), { target: { value: 'brandnew' } })
  fireEvent.change(screen.getByLabelText('Nhập lại mật khẩu mới'), { target: { value: 'brandnewX' } })
  fireEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
  expect(await screen.findByText('Hai ô mật khẩu mới không giống nhau.')).toBeTruthy()
  expect(change).not.toHaveBeenCalled()  // chưa từng chạm backend
})

test('surfaces the backend refusal instead of pretending it worked', async () => {
  vi.spyOn(api, 'getMe').mockResolvedValue({ authenticated: true, user: 'ceo' })
  vi.spyOn(api, 'changePassword').mockRejectedValue(new Error('Mật khẩu hiện tại không đúng.'))
  renderBox()
  await screen.findByText('Đổi mật khẩu đăng nhập')
  fireEvent.change(screen.getByLabelText('Mật khẩu hiện tại'), { target: { value: 'wrong' } })
  fireEvent.change(screen.getByLabelText('Mật khẩu mới'), { target: { value: 'brandnew' } })
  fireEvent.change(screen.getByLabelText('Nhập lại mật khẩu mới'), { target: { value: 'brandnew' } })
  fireEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
  expect(await screen.findByText('Mật khẩu hiện tại không đúng.')).toBeTruthy()
})
