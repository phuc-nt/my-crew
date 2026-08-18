// The assistant conversation's turn rules. The endpoint contract is exercised here so a
// change to /api/ops/chat's shape fails a test rather than the pane at runtime.
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { api } from '../../../api/client'
import { LanguageProvider } from '../../../i18n/language-context'
import { useOpsChat } from './use-ops-chat'

vi.mock('../../../api/client', () => ({
  api: {
    getOpsChatCommands: vi.fn(),
    opsChatAvailable: vi.fn(),
    opsChat: vi.fn(),
  },
}))

const mocked = vi.mocked(api)

function setup() {
  return renderHook(() => useOpsChat(), { wrapper: LanguageProvider })
}

beforeEach(() => {
  vi.clearAllMocks()
  mocked.getOpsChatCommands.mockResolvedValue({ commands: [] })
  mocked.opsChatAvailable.mockResolvedValue({ available: true })
  mocked.opsChat.mockResolvedValue({ reply: 'Đội hiện có 11 agent', agent_id: 'admin' })
})

describe('availability', () => {
  test('stays null until the probe answers, so the pane can show "checking"', async () => {
    const { result } = setup()
    expect(result.current.available).toBe(null)
    await waitFor(() => expect(result.current.available).toBe(true))
  })

  test('a failed probe reports unavailable with the reason rather than hanging', async () => {
    mocked.opsChatAvailable.mockRejectedValue(new Error('không có admin agent'))
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(false))
    expect(result.current.unavailableReason).toContain('admin')
  })

  test('a failed command catalog does not block the chat — it is discoverability only', async () => {
    mocked.getOpsChatCommands.mockRejectedValue(new Error('nope'))
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(true))
    expect(result.current.commands).toEqual([])
  })
})

describe('turns', () => {
  test('the CEO turn appears before the reply arrives', async () => {
    let resolve: (v: { reply: string; agent_id: string }) => void = () => {}
    mocked.opsChat.mockReturnValue(new Promise((r) => { resolve = r }))
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(true))

    act(() => void result.current.send('trạng thái'))
    await waitFor(() => expect(result.current.turns).toHaveLength(1))
    expect(result.current.turns[0]).toEqual({ who: 'ceo', text: 'trạng thái' })
    expect(result.current.busy).toBe(true)

    await act(async () => { resolve({ reply: 'xong', agent_id: 'admin' }) })
    await waitFor(() => expect(result.current.turns).toHaveLength(2))
    expect(result.current.turns[1]).toEqual({ who: 'agent', text: 'xong' })
  })

  test('busy stays true for the whole turn — the pane shows "working" meanwhile', async () => {
    // Measured against the live engine: the cost query takes ~5.6s. Without a busy flag
    // spanning the wait the CEO sees only their own message and assumes the send failed.
    let resolve: (v: { reply: string; agent_id: string }) => void = () => {}
    mocked.opsChat.mockReturnValue(new Promise((r) => { resolve = r }))
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(true))

    act(() => void result.current.send('tổng chi phí tháng này'))
    await waitFor(() => expect(result.current.busy).toBe(true))
    await act(async () => { resolve({ reply: 'xong', agent_id: 'admin' }) })
    await waitFor(() => expect(result.current.busy).toBe(false))
  })

  test('a second send is ignored while a turn is in flight', async () => {
    let resolve: (v: { reply: string; agent_id: string }) => void = () => {}
    mocked.opsChat.mockReturnValue(new Promise((r) => { resolve = r }))
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(true))

    act(() => void result.current.send('một'))
    await waitFor(() => expect(result.current.busy).toBe(true))
    await act(async () => { await result.current.send('hai') })
    expect(mocked.opsChat).toHaveBeenCalledTimes(1)
    await act(async () => { resolve({ reply: 'xong', agent_id: 'admin' }) })
  })

  test('an empty message sends nothing', async () => {
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(true))
    await act(async () => { await result.current.send('   ') })
    expect(mocked.opsChat).not.toHaveBeenCalled()
  })

  test('a failed send surfaces the error and leaves the CEO turn in place', async () => {
    mocked.opsChat.mockRejectedValue(new Error('engine sập'))
    const { result } = setup()
    await waitFor(() => expect(result.current.available).toBe(true))
    await act(async () => { await result.current.send('trạng thái') })
    expect(result.current.error).toContain('engine sập')
    expect(result.current.turns).toHaveLength(1)
    expect(result.current.busy).toBe(false)
  })
})
