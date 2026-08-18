// Pure conversation-list rules: what the left pane shows, in what order, and how many
// events each row still owes the reader. No React, no fetch — same posture as chat-state.ts.
//
// Unread deliberately derives from the room's `last_seq` (the workrooms join) rather than
// from the reducer's thread state: only `last_seq` is accurate for the whole history,
// because 127k rows mirrored before the provenance column existed cannot be attributed
// to any workroom. The live stream only bumps rooms it CAN attribute.
import type { Workroom } from '../../types'

/** The ops/assistant conversation. Not a workroom — it has no seq stream of its own. */
export const ASSISTANT_CONVERSATION_ID = '__assistant__'

const STORAGE_KEY = 'chat-read-cursors'

/** roomId → highest seq the reader has seen. */
export type ReadCursors = Record<string, number>

/**
 * Ceiling for a rendered unread badge (a real, known count above this reads as "99+").
 *
 * `last_seq` is the OFFICE-WIDE event counter, not a per-room count — measured on real
 * data, a room holding 36 events reported last_seq=114165. Once a room has been opened
 * the cursor is on the same global scale, so `last_seq - cursor` is an exact delta; it
 * is only the never-read case that has no lower bound to subtract, which is what
 * UNKNOWN_UNREAD below exists for. This constant caps a REAL count's rendering ("99+").
 */
export const MAX_UNSEEN_BADGE = 99

/**
 * Sentinel for "unread, amount unknown" — see MAX_UNSEEN_BADGE. Rendered as a dot, not a
 * number: on a real fleet EVERY never-opened room would otherwise show the same capped
 * figure (115 rooms all reading "99" carries no signal and misstates the count).
 */
export const UNKNOWN_UNREAD = -1

function unreadFor(lastSeq: number, cursor: number | undefined): number {
  if (lastSeq <= 0) return 0
  // Never opened: the delta would be the whole global counter, and there is no per-room
  // count in the payload to fall back on — so say "unread" without inventing a number.
  if (cursor === undefined) return UNKNOWN_UNREAD
  return Math.max(0, lastSeq - cursor)
}

export interface Conversation {
  id: string
  title: string
  /** Absent for the assistant row. */
  status?: Workroom['status']
  taskCount?: number
  updatedAt?: string
  unread: number
  isAssistant: boolean
}

/**
 * Build the ordered conversation list. The assistant row is pinned first — it is the
 * entry point for ops commands and fleet-wide questions, so it must not sink under
 * a hundred workrooms sorted by activity.
 */
export function buildConversations(
  rooms: readonly Workroom[],
  cursors: ReadCursors,
): Conversation[] {
  const workrooms = [...rooms]
    // Newest activity first. A missing/blank `updated_at` sorts last instead of throwing.
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
    .map<Conversation>((room) => ({
      id: room.room_id,
      title: room.title,
      status: room.status,
      taskCount: room.task_count,
      updatedAt: room.updated_at,
      unread: unreadFor(room.last_seq, cursors[room.room_id]),
      isAssistant: false,
    }))

  return [
    { id: ASSISTANT_CONVERSATION_ID, title: '', unread: 0, isAssistant: true },
    ...workrooms,
  ]
}

/** Badge total for the nav. The assistant row carries no seq stream, so it adds nothing. */
export function totalUnread(conversations: readonly Conversation[]): number {
  // UNKNOWN_UNREAD rooms are excluded: their count is unknown, and adding a placeholder
  // for each would make the fleet-wide total a fiction that grows with the room count.
  return conversations.reduce((sum, c) => (c.unread > 0 ? sum + c.unread : sum), 0)
}

/**
 * Read the persisted cursors. Any failure — storage absent (embedded webview, jsdom),
 * access denied, or corrupt JSON — degrades to "nothing read yet" rather than breaking
 * the whole pane. Non-numeric entries are dropped for the same reason.
 */
export function loadReadCursors(): ReadCursors {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(STORAGE_KEY)
  } catch {
    return {}
  }
  if (!raw) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const out: ReadCursors = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value)) out[key] = value
    }
    return out
  } catch {
    return {}
  }
}

/**
 * Mark `roomId` read up to `seq`, returning the next cursor map. The cursor only ever
 * moves forward: the thread view marks read with the tail's last seq, and a short tail
 * loaded after a long one must not resurrect already-read events as unread.
 */
export function markRead(cursors: ReadCursors, roomId: string, seq: number): ReadCursors {
  const current = cursors[roomId] ?? 0
  if (seq <= current) return cursors
  const next = { ...cursors, [roomId]: seq }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // Best-effort persistence; the in-memory map is still authoritative this session.
  }
  return next
}
