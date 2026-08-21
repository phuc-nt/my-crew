// v7 M17 Setup wizard tests: walks a group, tests a connection, advances, and finishes.
// Mocked api, no network (npm test).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Setup } from './Setup'

function renderSetup(onDone: () => void) {
  return render(
    <LanguageProvider>
      <Setup onDone={onDone} />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'setupEnv').mockResolvedValue({ ok: true, written: [] })
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'saveCompany').mockResolvedValue({
    name: '',
    coordinator_id: null,
    team_task_cap_usd: 2.0,
  })
})

// One extra "Công ty" step sits between the 5 key groups (openrouter, atlassian, slack,
// github, websearch) and the password step — walk it too (mocked api.saveCompany,
// asserted separately where relevant).
async function advanceThroughGroupsAndCompany() {
  for (let i = 0; i < 5; i++) {
    fireEvent.click(screen.getByText('Tiếp tục'))
    await waitFor(() => {}) // let saveGroup resolve
  }
  await waitFor(() => expect(screen.getByText('Công ty')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Tiếp tục'))
  await waitFor(() => {}) // let saveCompany resolve
}

test('renders the first group and can test the connection', async () => {
  const setupTest = vi
    .spyOn(api, 'setupTest')
    .mockResolvedValue({ group: 'openrouter', ok: true, detail: 'OK', hint: '' })
  renderSetup(vi.fn())
  expect(screen.getByText('OpenRouter (bộ não LLM)')).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-x' } })
  fireEvent.click(screen.getByText('Kiểm tra kết nối'))
  await waitFor(() => expect(screen.getByText(/Kết nối OK/)).toBeInTheDocument())
  expect(setupTest).toHaveBeenCalledWith('openrouter')
  expect(api.setupEnv).toHaveBeenCalled() // persisted before test
})

test('advances through groups to the password step and finishes', async () => {
  vi.spyOn(api, 'setupFinish').mockResolvedValue({
    ok: true,
    restarting: true,
    restart_hint: 'Dịch vụ chạy qua launchd — tự khởi động lại, đợi ~5 giây rồi đăng nhập.',
    message: 'restarting',
  })
  vi.spyOn(api, 'setupStatus').mockResolvedValue({ completed: true })
  const onDone = vi.fn()
  renderSetup(onDone)

  // click "Tiếp tục" through the 4 groups + company step → password step
  await advanceThroughGroupsAndCompany()
  await waitFor(() => expect(screen.getByText('Đặt mật khẩu đăng nhập')).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: 'ceopass' } })
  fireEvent.click(screen.getByText('Hoàn tất & khởi động'))
  await waitFor(() => expect(screen.getByText(/Đang khởi động lại/)).toBeInTheDocument())
  expect(api.setupFinish).toHaveBeenCalledWith('admin', 'ceopass')
  // the server-supplied restart hint is shown, not a hardcoded string
  await waitFor(() =>
    expect(screen.getByText(/Dịch vụ chạy qua launchd/)).toBeInTheDocument(),
  )
  await waitFor(() => expect(onDone).toHaveBeenCalled())
})

test('a bricked finish (network error mid-restart) polls setup/status instead of showing finishFailed', async () => {
  // The restart kills the process before the HTTP response flushes — fetch rejects with
  // a raw network error, not an ApiError. This must NOT show "hoàn tất thất bại"; it
  // must poll /api/setup/status until completed, then call onDone.
  vi.spyOn(api, 'setupFinish').mockRejectedValue(new TypeError('Failed to fetch'))
  const setupStatus = vi.spyOn(api, 'setupStatus').mockResolvedValue({ completed: true })
  const onDone = vi.fn()
  renderSetup(onDone)

  await advanceThroughGroupsAndCompany()
  await waitFor(() => expect(screen.getByText('Đặt mật khẩu đăng nhập')).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: 'ceopass' } })
  fireEvent.click(screen.getByText('Hoàn tất & khởi động'))

  await waitFor(() => expect(screen.getByText(/Đang khởi động lại/)).toBeInTheDocument())
  expect(screen.queryByText('hoàn tất thất bại')).toBeNull()
  await waitFor(() => expect(setupStatus).toHaveBeenCalled())
  await waitFor(() => expect(onDone).toHaveBeenCalled())
})

test('a 410 from finish (wizard already locked) also polls instead of erroring', async () => {
  vi.spyOn(api, 'setupFinish').mockRejectedValue(new ApiError(410, 'setup already completed'))
  vi.spyOn(api, 'setupStatus').mockResolvedValue({ completed: true })
  const onDone = vi.fn()
  renderSetup(onDone)

  await advanceThroughGroupsAndCompany()
  await waitFor(() => expect(screen.getByText('Đặt mật khẩu đăng nhập')).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: 'ceopass' } })
  fireEvent.click(screen.getByText('Hoàn tất & khởi động'))

  await waitFor(() => expect(screen.getByText(/Đang khởi động lại/)).toBeInTheDocument())
  await waitFor(() => expect(onDone).toHaveBeenCalled())
})

test('a genuine finish validation error (non-410 ApiError) still shows finishFailed-style message', async () => {
  vi.spyOn(api, 'setupFinish').mockRejectedValue(new ApiError(400, 'invalid username'))
  const onDone = vi.fn()
  renderSetup(onDone)

  await advanceThroughGroupsAndCompany()
  await waitFor(() => expect(screen.getByText('Đặt mật khẩu đăng nhập')).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: 'ceopass' } })
  fireEvent.click(screen.getByText('Hoàn tất & khởi động'))

  await waitFor(() => expect(screen.getByText('invalid username')).toBeInTheDocument())
  expect(onDone).not.toHaveBeenCalled()
})

test('short password blocks finish', async () => {
  const finish = vi.spyOn(api, 'setupFinish')
  renderSetup(vi.fn())
  await advanceThroughGroupsAndCompany()
  await screen.findByText('Đặt mật khẩu đăng nhập')
  fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: '12' } })
  // button disabled at <6 chars → finish never called
  expect(screen.getByText('Hoàn tất & khởi động')).toBeDisabled()
  expect(finish).not.toHaveBeenCalled()
})

test('company step writes name + chosen coordinator via POST /api/company', async () => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'default', name: 'Default Agent', enabled: true, last_run: null },
  ])
  const saveCompany = vi.spyOn(api, 'saveCompany').mockResolvedValue({
    name: 'Acme JSC',
    coordinator_id: 'default',
    team_task_cap_usd: 2.0,
  })
  renderSetup(vi.fn())

  for (let i = 0; i < 5; i++) {
    fireEvent.click(screen.getByText('Tiếp tục'))
    await waitFor(() => {})
  }
  await waitFor(() => expect(screen.getByText('Công ty')).toBeInTheDocument())
  await waitFor(() => expect(screen.getByText(/Default Agent/)).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText('Tên công ty'), { target: { value: 'Acme JSC' } })
  fireEvent.change(screen.getByLabelText(/Trưởng phòng/), { target: { value: 'default' } })
  fireEvent.click(screen.getByText('Tiếp tục'))

  await waitFor(() => expect(screen.getByText('Đặt mật khẩu đăng nhập')).toBeInTheDocument())
  expect(saveCompany).toHaveBeenCalledWith('Acme JSC', 'default')
})
