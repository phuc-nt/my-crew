// Office group-chat room (v12 M29): the team's shared timeline — CEO briefs, task
// assignments, step progress, handoffs, and milestones — rendered as a chat-like log,
// matching Chat.tsx's ops-chat-* styling conventions. Room picker on the left (via
// GET /api/office/rooms), live timeline via SSE store-tail (use-office-stream.ts).
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { useOfficeStream } from '../hooks/use-office-stream'
// v15: line rendering shared with the unified office screen's activity feed — one
// vocabulary, one place to extend (see office-shared/office-message-line.ts).
import { KIND_LABEL, messageLine } from './office-shared/office-message-line'

const OFFICE_ROOM_ID = 'office'

export function OfficeRoom() {
  const [rooms, setRooms] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const activeRoom = searchParams.get('room') ?? OFFICE_ROOM_ID

  const loadRooms = useCallback(() => {
    api
      .getOfficeRooms()
      .then((p) => setRooms(p.rooms))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'tải thất bại'))
  }, [])

  useEffect(() => {
    loadRooms()
  }, [loadRooms])

  const { messages, connected, errored } = useOfficeStream(activeRoom)

  const selectRoom = (roomId: string) => setSearchParams({ room: roomId })

  return (
    <section className="office-room">
      <h2>Văn phòng</h2>
      <p className="ops-chat-hint">
        Dòng thời gian hoạt động của cả đội: giao việc, phân công, tiến độ, bàn giao và các cột
        mốc quan trọng.
      </p>
      {error && <p className="error">Lỗi: {error}</p>}
      <div className="office-room-layout">
        <nav className="office-room-picker" aria-label="Danh sách phòng">
          <Button
            variant="chip"
            className={activeRoom === OFFICE_ROOM_ID ? 'chip-active' : undefined}
            onClick={() => selectRoom(OFFICE_ROOM_ID)}
          >
            Tổng quan
          </Button>
          {rooms
            ?.filter((r) => r !== OFFICE_ROOM_ID)
            .map((r) => (
              <Button
                key={r}
                variant="chip"
                className={activeRoom === r ? 'chip-active' : undefined}
                onClick={() => selectRoom(r)}
              >
                Việc #{r}
              </Button>
            ))}
        </nav>
        <div className="office-room-timeline">
          <p className="office-room-status">
            {errored ? 'Mất kết nối luồng — thử tải lại trang.' : connected ? 'Đang theo dõi trực tiếp' : 'Đang kết nối…'}
          </p>
          {messages.length === 0 && !errored && (
            <EmptyState>Chưa có hoạt động nào trong phòng này.</EmptyState>
          )}
          <ul className="office-room-log">
            {messages.map((m) => (
              <li key={m.seq} className={`office-room-entry office-room-${m.kind}`}>
                <span className="office-room-kind">{KIND_LABEL[m.kind] ?? m.kind}</span>
                <span className="office-room-author">{m.author}</span>
                <p className="office-room-text">{messageLine(m)}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
