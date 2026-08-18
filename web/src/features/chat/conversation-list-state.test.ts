// Pure conversation-list rules: ordering, unread, and the per-room read cursor.
import { beforeEach, describe, expect, test, vi } from 'vitest'
import type { Workroom } from '../../types'
import {
  ASSISTANT_CONVERSATION_ID,
  buildConversations,
  MAX_UNSEEN_BADGE,
  UNKNOWN_UNREAD,
  loadReadCursors,
  markRead,
  totalUnread,
} from './conversation-list-state'

function room(id: string, updated: string, lastSeq = 0, title = `Việc ${id}`): Workroom {
  return {
    room_id: id,
    title,
    task_count: 1,
    status: 'dang-chay',
    updated_at: updated,
    last_seq: lastSeq,
  }
}

describe('conversation ordering', () => {
  test('the assistant thread is always first, regardless of room activity', () => {
    // It is the only conversation that is never "stale" — it is where ops commands and
    // fleet-wide answers land, so burying it under 115 workrooms would hide the entry point.
    const c = buildConversations([room('a', '2026-08-18T12:00:00Z')], {})
    expect(c[0].id).toBe(ASSISTANT_CONVERSATION_ID)
  })

  test('workrooms sort by most recent activity first', () => {
    const c = buildConversations(
      [
        room('old', '2026-08-01T00:00:00Z'),
        room('new', '2026-08-18T00:00:00Z'),
        room('mid', '2026-08-10T00:00:00Z'),
      ],
      {},
    )
    expect(c.slice(1).map((x) => x.id)).toEqual(['new', 'mid', 'old'])
  })

  test('a room with no updated_at sinks to the bottom instead of throwing', () => {
    const rooms = [room('a', ''), room('b', '2026-08-10T00:00:00Z')]
    const c = buildConversations(rooms, {})
    expect(c.slice(1).map((x) => x.id)).toEqual(['b', 'a'])
  })
})

describe('unread per conversation', () => {
  test('unread is last_seq minus the stored cursor', () => {
    const c = buildConversations([room('a', 't', 10)], { a: 4 })
    expect(c.find((x) => x.id === 'a')?.unread).toBe(6)
  })

  test('a never-opened room reports "unread, count unknown" — see the global-seq note below', () => {
    const c = buildConversations([room('a', 't', 3)], {})
    expect(c.find((x) => x.id === 'a')?.unread).toBe(UNKNOWN_UNREAD)
  })

  test('a fully read room shows zero', () => {
    const c = buildConversations([room('a', 't', 7)], { a: 7 })
    expect(c.find((x) => x.id === 'a')?.unread).toBe(0)
  })

  test('total unread sums known counts only — unopened rooms contribute no fiction', () => {
    // 'b' was never opened, so its count is unknown; only 'a' has a real delta (5-1).
    const c = buildConversations([room('a', 't', 5), room('b', 't2', 3)], { a: 1 })
    expect(totalUnread(c)).toBe(4)
  })
})

describe('read cursors', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    })
  })

  test('marking a room read persists its cursor and clears the badge', () => {
    const next = markRead({}, 'room-a', 12)
    expect(next['room-a']).toBe(12)
    expect(loadReadCursors()['room-a']).toBe(12)
  })

  test('a cursor never moves backwards — reopening an old tail keeps the newer mark', () => {
    // The thread view marks read with the tail's last seq; a short tail after a long one
    // must not resurrect already-read events as unread.
    const next = markRead({ 'room-a': 20 }, 'room-a', 12)
    expect(next['room-a']).toBe(20)
  })

  test('corrupt stored JSON is ignored rather than crashing the list', () => {
    localStorage.setItem('chat-read-cursors', '{not json')
    expect(loadReadCursors()).toEqual({})
  })

  test('non-numeric stored values are dropped', () => {
    localStorage.setItem('chat-read-cursors', '{"a": "x", "b": 4}')
    expect(loadReadCursors()).toEqual({ b: 4 })
  })
})

describe('storage-less environments', () => {
  test('cursors degrade to in-memory when localStorage throws', () => {
    // Same posture as ui-mode/theme contexts: embedded webviews can throw on access.
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      },
    })
    expect(loadReadCursors()).toEqual({})
    expect(markRead({}, 'room-a', 5)['room-a']).toBe(5) // state still advances
  })
})

describe('unread against a GLOBAL seq counter', () => {
  // Measured on real data: `last_seq` is the office-wide event counter, not a per-room
  // count. A real room had last_seq=114165 with only 36 events in it. Subtracting a
  // zero cursor would badge "114165 unread" for every room the reader never opened.
  test('a never-opened room does not badge the whole global counter', () => {
    const c = buildConversations([room('a', 't', 114_165)], {})
    expect(c.find((x) => x.id === 'a')?.unread).toBe(UNKNOWN_UNREAD)
  })

  test('every unopened room reads the same — the dot is a state, not a count', () => {
    // On the live fleet 115 of 116 rooms are unopened. Capped numbers made them all read
    // "99", which looks like a measurement and is not one.
    const c = buildConversations([room('a', 't', 114_165), room('b', 't2', 36)], {})
    expect(c[1].unread).toBe(c[2].unread)
  })

  test('a large REAL delta still renders as a number, capped at 99+ by the view', () => {
    const c = buildConversations([room('a', 't', 114_165)], { a: 113_000 })
    expect(c.find((x) => x.id === 'a')?.unread).toBeGreaterThan(MAX_UNSEEN_BADGE)
  })

  test('once read, the delta against the global counter is exact', () => {
    // Cursor and last_seq are both global, so their difference is a true event delta.
    const c = buildConversations([room('a', 't', 114_165)], { a: 114_160 })
    expect(c.find((x) => x.id === 'a')?.unread).toBe(5)
  })

  test('the cap only applies to the unread case, never to a read room at zero', () => {
    const c = buildConversations([room('a', 't', 114_165)], { a: 114_165 })
    expect(c.find((x) => x.id === 'a')?.unread).toBe(0)
  })
})
