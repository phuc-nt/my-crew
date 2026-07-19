// v6 M14b Chat view tests: renders the ops dialogue, sends a message to /api/ops/chat and
// shows the agent reply; disables the box when no admin ops agent is available. Mocked api,
// no network (npm test).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Chat } from './Chat'

beforeEach(() => {
  vi.restoreAllMocks()
})

// Chat now reads ?intent= and renders a <Link>, so it needs a router context.
function renderChat(initialPath = '/chat') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LanguageProvider>
        <Chat />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

test('sends a message and renders the agent reply', async () => {
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({ available: true, agent_id: 'admin' })
  const opsChat = vi
    .spyOn(api, 'opsChat')
    .mockResolvedValue({ reply: 'Đội hiện có 3 agent', agent_id: 'admin' })
  renderChat()

  const input = await screen.findByPlaceholderText('Nhắn cho trợ lý…')
  fireEvent.change(input, { target: { value: 'đội mình sao rồi' } })
  fireEvent.click(screen.getByText('Gửi'))

  await waitFor(() => expect(screen.getByText('Đội hiện có 3 agent')).toBeInTheDocument())
  expect(opsChat).toHaveBeenCalledWith('đội mình sao rồi')
  // the CEO's own message is echoed in the log
  expect(screen.getByText('đội mình sao rồi')).toBeInTheDocument()
})

test('shows the unavailable reason when no admin ops agent exists', async () => {
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({
    available: false,
    reason: 'Chưa có agent quản trị',
  })
  renderChat()
  await waitFor(() => expect(screen.getByText(/Chưa có agent quản trị/)).toBeInTheDocument())
  expect(screen.queryByPlaceholderText('Nhắn cho trợ lý…')).not.toBeInTheDocument()
})

test('does not send an empty message', async () => {
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({ available: true, agent_id: 'admin' })
  const opsChat = vi.spyOn(api, 'opsChat').mockResolvedValue({ reply: 'x', agent_id: 'admin' })
  renderChat()
  await screen.findByPlaceholderText('Nhắn cho trợ lý…')
  // button disabled with empty draft → clicking does nothing
  fireEvent.click(screen.getByText('Gửi'))
  expect(opsChat).not.toHaveBeenCalled()
})

test('?intent=create-agent prefills a starter prompt in the input (v9 P2)', async () => {
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({ available: true, agent_id: 'admin' })
  renderChat('/chat?intent=create-agent')
  const input = (await screen.findByPlaceholderText('Nhắn cho trợ lý…')) as HTMLInputElement
  expect(input.value).toMatch(/Tạo nhân sự ảo mới/)
})

test('unavailable chat still offers the wizard fallback link (no dead-end, red-team B3)', async () => {
  vi.spyOn(api, 'opsChatAvailable').mockResolvedValue({
    available: false,
    reason: 'Chưa có agent quản trị',
  })
  renderChat()
  const link = await screen.findByText(/tạo nhân sự ảo bằng biểu mẫu/i)
  expect(link.closest('a')).toHaveAttribute('href', '/create')
})
