// Wire-contract pin: `use-office-stream.ts` listens ONLY via `es.onmessage`, which the
// EventSource spec fires exclusively for UNNAMED (default `message`-type) frames. The
// backend (`routes_office_stream.py`) emits frames with no `event:` field so `kind`
// rides inside the JSON `data` payload instead — this test feeds a real `MessageEvent`
// through a fake `EventSource`'s `onmessage` handler (the exact channel a browser uses
// for an unnamed frame) and asserts the event lands, proving the frontend side of the
// contract independently of the backend.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearOfficeStreamCache, useOfficeStream } from './use-office-stream'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  clearOfficeStreamCache()
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('an unnamed message frame (onmessage) lands in the hook state, matching the real wire contract', async () => {
  const { result } = renderHook(() => useOfficeStream('office'))

  const es = FakeEventSource.instances[0]
  expect(es).toBeDefined()
  expect(es.url).toBe('/api/office/rooms/office/stream')

  act(() => {
    es.onopen?.()
    es.onmessage?.({
      data: JSON.stringify({
        seq: 1, ts: 't', author: 'coordinator', kind: 'assignment',
        body: { task_title: 'Demo', step_count: 2, summary: 'phân công' },
      }),
    })
  })

  await waitFor(() => expect(result.current.messages).toHaveLength(1))
  expect(result.current.connected).toBe(true)
  expect(result.current.messages[0]).toMatchObject({ seq: 1, kind: 'assignment' })
})

test('duplicate seq delivered twice (a reconnect replay) is deduped to one message', async () => {
  const { result } = renderHook(() => useOfficeStream('office'))
  const es = FakeEventSource.instances[0]
  const frame = { data: JSON.stringify({ seq: 5, ts: 't', author: 'ceo', kind: 'ceo', body: { text: 'go' } }) }

  act(() => {
    es.onmessage?.(frame)
    es.onmessage?.(frame)
  })

  await waitFor(() => expect(result.current.messages).toHaveLength(1))
})

test('a re-mount seeds messages from the room cache and connects with ?since_seq=', async () => {
  const first = renderHook(() => useOfficeStream('office'))
  const es1 = FakeEventSource.instances[0]
  expect(es1.url).toBe('/api/office/rooms/office/stream') // cold connect: full replay

  act(() => {
    es1.onmessage?.({
      data: JSON.stringify({ seq: 7, ts: 't', author: 'ceo', kind: 'ceo', body: { text: 'go' } }),
    })
  })
  await waitFor(() => expect(first.result.current.messages).toHaveLength(1))
  first.unmount()

  const second = renderHook(() => useOfficeStream('office'))
  const es2 = FakeEventSource.instances[1]
  // Warm re-mount: cached history shows immediately, wire asks only for newer rows.
  expect(second.result.current.messages).toHaveLength(1)
  expect(es2.url).toBe('/api/office/rooms/office/stream?since_seq=7')

  act(() => {
    es2.onmessage?.({
      data: JSON.stringify({ seq: 8, ts: 't', author: 'ceo', kind: 'ceo', body: { text: 'ok' } }),
    })
  })
  await waitFor(() => expect(second.result.current.messages).toHaveLength(2))
  expect(second.result.current.messages.map((m) => m.seq)).toEqual([7, 8])
})

test('onerror marks the stream disconnected and errored', async () => {
  const { result } = renderHook(() => useOfficeStream('office'))
  const es = FakeEventSource.instances[0]

  act(() => {
    es.onerror?.()
  })

  await waitFor(() => expect(result.current.errored).toBe(true))
  expect(result.current.connected).toBe(false)
})
