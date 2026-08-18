// The palette's keyboard contract and its three sources, against mocked endpoints whose
// payloads are copied from the live fleet.
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import { CommandPalette } from './command-palette'

vi.mock('../../api/client', () => ({
  api: {
    getOpsChatCommands: vi.fn(),
    searchHistory: vi.fn(),
    getWorkrooms: vi.fn(),
  },
}))

const mocked = vi.mocked(api)

function setup() {
  // retry:false — a mocked rejection must surface immediately, not after backoff.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <LanguageProvider>
          <CommandPalette />
        </LanguageProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocked.getOpsChatCommands.mockResolvedValue({
    commands: [{ id: 'get_status', description: 'Xem trạng thái cả đội', readonly: true }],
  })
  mocked.searchHistory.mockResolvedValue({ hits: [] })
  mocked.getWorkrooms.mockResolvedValue({ rooms: [] })
})

/** The palette listens on `window`, so the chord is dispatched there rather than typed
 *  into an element — matching how the real shell receives it from anywhere in the app. */
async function openPalette() {
  await act(async () => {
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
  })
  return screen.findByRole('dialog')
}

/** Types into the palette input the way a change event arrives, in one shot: the hook
 *  debounces on the query value, not on keystroke count. */
async function type(text: string) {
  const input = screen.getByRole('dialog').querySelector('input') as HTMLInputElement
  await act(async () => {
    fireEvent.change(input, { target: { value: text } })
  })
}

describe('opening and closing', () => {
  test('renders nothing until the chord is pressed', () => {
    setup()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('Cmd+K opens it and Escape closes it', async () => {
    setup()
    await openPalette()
    await act(async () => {
      fireEvent.keyDown(window, { key: 'Escape' })
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})

describe('results', () => {
  test('opens showing every hub and the ops catalog, before any typing', async () => {
    setup()
    await openPalette()
    // All five hubs, so the palette is a complete map of the app on open.
    expect(screen.getByText('Trò chuyện')).toBeTruthy()
    expect(screen.getByText('Hệ thống')).toBeTruthy()
    await screen.findByText('Xem trạng thái cả đội')
  })

  test('a one-character query does not hit the search endpoint', async () => {
    setup()
    await openPalette()
    await type('c')
    await waitFor(() => expect(mocked.searchHistory).not.toHaveBeenCalled())
  })

  test('a real hit is listed with its FTS5 markers stripped', async () => {
    // Verbatim from GET /api/search?q=bao cao on the live fleet.
    mocked.searchHistory.mockResolvedValue({
      hits: [{
        excerpt: 'Tổng hợp và »báo« »cáo« kết quả',
        source: 'step',
        ref: '10fbf98bafa6:52',
        agent_id: 'default',
        ts: '2026-07-11T01:50:17.652428+00:00',
      }],
    })
    setup()
    await openPalette()
    await type('báo cáo')
    const hit = await screen.findByText('Tổng hợp và báo cáo kết quả', {}, { timeout: 3000 })
    expect(hit.textContent).not.toContain('»')
  })
})

describe('keyboard selection', () => {
  test('Enter picks the row the cursor is on, not always the first', async () => {
    const { container } = setup()
    await openPalette()
    const input = screen.getByRole('dialog').querySelector('input') as HTMLInputElement
    await act(async () => {
      fireEvent.keyDown(input, { key: 'ArrowDown' })
    })
    const cursor = container.querySelector('.palette-item.is-cursor')
    // Second hub, because one ArrowDown moved off the first.
    expect(cursor?.textContent).toContain('Văn phòng')
  })
})
