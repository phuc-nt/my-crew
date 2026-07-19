// v33 P1: Connections view — renders cards with presence-only key state, saves keys
// through the client, shows the restart banner and the honest dev-mode restart message.
// Mocked api, no network.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Connections } from './Connections'
import type { ConnectionsPayload } from '../types'

function renderConnections() {
  return render(
    <LanguageProvider>
      <Connections />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

const payload: ConnectionsPayload = {
  needs_restart: false,
  cards: [
    {
      id: 'websearch',
      label: 'Tìm kiếm web (Tavily / Brave)',
      ok: false,
      detail: 'agents bật web_search: nghien-cuu — THIẾU key',
      hint: 'Thêm TAVILY_API_KEY hoặc BRAVE_API_KEY',
      note: '',
      keys: [
        { name: 'TAVILY_API_KEY', set: false },
        { name: 'BRAVE_API_KEY', set: true },
      ],
    },
    {
      id: 'nokey',
      label: 'Firecrawl / OpenAlex',
      ok: true,
      detail: '',
      hint: '',
      note: 'Không cần key — Firecrawl chạy local, OpenAlex là API mở.',
      keys: [],
    },
  ],
}

test('renders cards with presence state, never an input value', async () => {
  vi.spyOn(api, 'getConnections').mockResolvedValue(payload)
  renderConnections()

  expect(await screen.findByText('Tìm kiếm web (Tavily / Brave)')).toBeInTheDocument()
  expect(screen.getByText('TAVILY_API_KEY')).toBeInTheDocument()
  expect(screen.getByText('chưa đặt')).toBeInTheDocument()
  expect(screen.getByText('đã đặt')).toBeInTheDocument()
  // no-key card renders its note and no form
  expect(
    screen.getByText('Không cần key — Firecrawl chạy local, OpenAlex là API mở.'),
  ).toBeInTheDocument()
  // inputs are password-type and empty (a stored value never round-trips)
  const input = screen.getByPlaceholderText('chưa đặt — nhập giá trị')
  expect(input).toHaveAttribute('type', 'password')
  expect(input).toHaveValue('')
})

test('saves entered keys and reloads with the restart banner', async () => {
  const get = vi
    .spyOn(api, 'getConnections')
    .mockResolvedValueOnce(payload)
    .mockResolvedValueOnce({ ...payload, needs_restart: true })
  const putKeys = vi.spyOn(api, 'putConnectionKeys').mockResolvedValue({
    ok: true,
    written: ['TAVILY_API_KEY'],
    needs_restart: true,
  })
  renderConnections()

  const input = await screen.findByPlaceholderText('chưa đặt — nhập giá trị')
  fireEvent.change(input, { target: { value: 'tvly-abc' } })
  fireEvent.click(screen.getByRole('button', { name: 'Lưu' }))

  await waitFor(() =>
    expect(putKeys).toHaveBeenCalledWith({ TAVILY_API_KEY: 'tvly-abc' }),
  )
  expect(await screen.findByText(/cần khởi động lại máy chủ/)).toBeInTheDocument()
  expect(get).toHaveBeenCalledTimes(2)
})

test('restart asks for confirmation and shows the honest dev message', async () => {
  vi.spyOn(api, 'getConnections').mockResolvedValue({ ...payload, needs_restart: true })
  const restart = vi.spyOn(api, 'restartService').mockResolvedValue({
    ok: true,
    managed: false,
    message: 'Dịch vụ không chạy qua launchd — hãy khởi động lại thủ công.',
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderConnections()

  fireEvent.click(await screen.findByRole('button', { name: 'Khởi động lại' }))
  await waitFor(() => expect(restart).toHaveBeenCalled())
  expect(await screen.findByText(/khởi động lại thủ công/)).toBeInTheDocument()
})

test('restart is not called when the user cancels the confirm', async () => {
  vi.spyOn(api, 'getConnections').mockResolvedValue({ ...payload, needs_restart: true })
  const restart = vi.spyOn(api, 'restartService')
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  renderConnections()

  fireEvent.click(await screen.findByRole('button', { name: 'Khởi động lại' }))
  expect(restart).not.toHaveBeenCalled()
})
