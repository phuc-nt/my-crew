// Room-scoped SSE subscription for the office group-chat timeline (v12 M29). Mirrors
// use-sse.ts's shape (EventSource, done/errored distinction) but is ROOM-scoped and
// NEVER "done" — a room's stream has no terminal frame (store-tail keeps polling
// forever), so this hook's only terminal state is a dropped connection.
//
// Resume (two layers):
//   1. Browser reconnect — EventSource sends `Last-Event-ID` automatically, no
//      bookkeeping needed.
//   2. Re-MOUNT (room switch, navigating away and back) — a fresh EventSource has no
//      Last-Event-ID, so without help every mount replays the room from seq 0. The
//      module-level cache below keeps each room's messages + last seq across mounts;
//      a warm re-mount seeds from the cache and connects with `?since_seq=` (the
//      server-side cursor `routes_office_stream.py` already supports), so only NEW
//      rows travel the wire. Cold first connect keeps the bare URL (full replay).
import { useEffect, useRef, useState } from 'react'
import type { OfficeMessage } from '../types'

interface RoomStreamCache {
  messages: OfficeMessage[]
  seen: Set<number>
  lastSeq: number
}

const roomCache = new Map<string, RoomStreamCache>()

function cacheFor(roomId: string): RoomStreamCache {
  let entry = roomCache.get(roomId)
  if (!entry) {
    entry = { messages: [], seen: new Set(), lastSeq: 0 }
    roomCache.set(roomId, entry)
  }
  return entry
}

// Test hook — vitest keeps module state alive between tests in one file.
export function clearOfficeStreamCache(): void {
  roomCache.clear()
}

export function useOfficeStream(roomId: string | null): {
  messages: OfficeMessage[]
  connected: boolean
  errored: boolean
} {
  const [messages, setMessages] = useState<OfficeMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [errored, setErrored] = useState(false)
  // Mirrors the cache entry for the active room so onmessage never touches a stale one.
  const cacheRef = useRef<RoomStreamCache | null>(null)

  useEffect(() => {
    if (!roomId) return
    const cache = cacheFor(roomId)
    cacheRef.current = cache
    setMessages([...cache.messages])
    setConnected(false)
    setErrored(false)

    const base = `/api/office/rooms/${encodeURIComponent(roomId)}/stream`
    const url = cache.lastSeq > 0 ? `${base}?since_seq=${cache.lastSeq}` : base
    const es = new EventSource(url)
    es.onopen = () => setConnected(true)
    es.onmessage = (m) => {
      try {
        const parsed = JSON.parse(m.data) as OfficeMessage
        // A reconnect can briefly re-deliver the boundary row — dedup by seq so the
        // timeline never shows a duplicate entry.
        if (cache.seen.has(parsed.seq)) return
        cache.seen.add(parsed.seq)
        cache.messages.push(parsed)
        if (parsed.seq > cache.lastSeq) cache.lastSeq = parsed.seq
        setMessages([...cache.messages])
      } catch {
        /* ignore a malformed frame */
      }
    }
    es.onerror = () => {
      setConnected(false)
      setErrored(true)
    }
    return () => {
      es.close()
      setConnected(false)
    }
  }, [roomId])

  return { messages, connected, errored }
}
