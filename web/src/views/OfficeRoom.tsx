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
import { useLanguage } from '../i18n/language-context'
// v15: line rendering shared with the unified office screen's activity feed — one
// vocabulary, one place to extend (see office-shared/office-message-line.ts).
import { kindLabel, messageLine } from './office-shared/office-message-line'

const OFFICE_ROOM_ID = 'office'

export function OfficeRoom() {
  const { t } = useLanguage()
  const [rooms, setRooms] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const activeRoom = searchParams.get('room') ?? OFFICE_ROOM_ID

  const loadRooms = useCallback(() => {
    api
      .getOfficeRooms()
      .then((p) => setRooms(p.rooms))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('officeRoom.loadFailed')))
  }, [t])

  useEffect(() => {
    loadRooms()
  }, [loadRooms])

  const { messages, connected, errored } = useOfficeStream(activeRoom)

  const selectRoom = (roomId: string) => setSearchParams({ room: roomId })

  return (
    <section className="office-room">
      <h2>{t('officeRoom.title')}</h2>
      <p className="ops-chat-hint">{t('officeRoom.hint')}</p>
      {error && <p className="error">{t('officeRoom.errorPrefix', { message: error })}</p>}
      <div className="office-room-layout">
        <nav className="office-room-picker" aria-label={t('officeRoom.roomsAriaLabel')}>
          <Button
            variant="chip"
            className={activeRoom === OFFICE_ROOM_ID ? 'chip-active' : undefined}
            onClick={() => selectRoom(OFFICE_ROOM_ID)}
          >
            {t('officeRoom.overview')}
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
                {t('officeRoom.roomLabel', { room: r })}
              </Button>
            ))}
        </nav>
        <div className="office-room-timeline">
          <p className="office-room-status">
            {errored
              ? t('officeRoom.disconnected')
              : connected
                ? t('officeRoom.connected')
                : t('officeRoom.connecting')}
          </p>
          {messages.length === 0 && !errored && <EmptyState>{t('officeRoom.empty')}</EmptyState>}
          <ul className="office-room-log">
            {messages.map((m) => (
              <li key={m.seq} className={`office-room-entry office-room-${m.kind}`}>
                <span className="office-room-kind">{kindLabel(m.kind, t)}</span>
                <span className="office-room-author">{m.author}</span>
                <p className="office-room-text">{messageLine(m, t)}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
