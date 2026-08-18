// Center pane: one room's conversation. Subscribes to that room's SSE stream and folds
// it through the pure reducer — this component owns scrolling and the read cursor, and
// nothing else. Every display rule lives in chat-state.ts.
import { useEffect, useMemo, useRef } from 'react'
import { useLanguage } from '../../i18n/language-context'
import { useOfficeStream } from '../../hooks/use-office-stream'
import { OVERVIEW_ROOM_ID, reduceThread } from './chat-state'
import { MessageRow } from './messages/message-renderer'

/** The overview room mirrors every event ever written, so a cold connect asks for a tail
 *  instead of the whole company history. A workroom's history IS its conversation. */
const OVERVIEW_COLD_TAIL = 200

interface Props {
  roomId: string
  title: string
  /** Called with the room's highest seq once rendered, so the badge can clear. */
  onRead: (roomId: string, seq: number) => void
}

export function ThreadView({ roomId, title, onRead }: Props) {
  const { t } = useLanguage()
  const coldTail = roomId === OVERVIEW_ROOM_ID ? OVERVIEW_COLD_TAIL : undefined
  const { messages, connected, errored } = useOfficeStream(roomId, coldTail)
  const listRef = useRef<HTMLUListElement>(null)

  const thread = useMemo(() => reduceThread(messages, roomId), [messages, roomId])

  // Reading the thread IS reading the room: mark up to the highest seq rendered.
  useEffect(() => {
    if (thread.lastSeq > 0) onRead(roomId, thread.lastSeq)
  }, [roomId, thread.lastSeq, onRead])

  // Follow the tail. Chat's expectation is the newest message on screen, and the reducer
  // only ever appends (or folds into) the last item, so an unconditional scroll matches.
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [thread.items.length])

  const status = errored
    ? t('activityFeed.disconnected')
    : connected
      ? t('activityFeed.connected')
      : t('activityFeed.connecting')

  return (
    <section className="chat-thread" aria-label={title}>
      <header className="chat-thread-head">
        {/* The full brief lives here (the rows no longer repeat it), clamped to one line
                  so a 120-char title cannot eat the thread's height; hover shows it whole. */}
              <h2 className="chat-thread-title" title={title}>{title}</h2>
        <span className="chat-thread-status">{status}</span>
      </header>

      <ul className="chat-thread-log" ref={listRef}>
        {thread.items.length === 0 ? (
          <li className="chat-thread-empty">{t('chat.threadEmpty')}</li>
        ) : (
          thread.items.map((item) => <MessageRow key={item.seq} item={item} />)
        )}
      </ul>

      {thread.activities.length > 0 ? (
        <ul className="chat-activities" aria-label={t('chat.activityLabel')}>
          {thread.activities.map((a) => (
            <li key={`${a.task ?? ''} ${a.step ?? ''}`} className="chat-activity">
              {t('chat.activityLine', {
                step: a.step ?? '',
                tool: a.tool ?? '',
                count: a.count ?? 0,
              })}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
