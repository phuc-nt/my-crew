// The chat hub: conversation list · thread · pending pane.
//
// Composition over rewrite — the composer is the SAME `AssignComposer` the office screen
// uses. Its intent flow (preview → confirm, adjust → confirm-adjust, question → reply)
// with @mention picking is already built and tested against the real endpoints; a second
// implementation here would be a second thing to keep correct.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { useWorkrooms } from '../../api/queries/use-office-queries'
import { useLanguage } from '../../i18n/language-context'
import { AssignComposer } from '../shared/assign-composer'
import { OVERVIEW_ROOM_ID } from './chat-state'
import { ConversationList } from './conversation-list'
import { AssistantThread } from './assistant/assistant-thread'
import { PendingPane } from './pending/pending-pane'
import {
  ASSISTANT_CONVERSATION_ID,
  buildConversations,
  loadReadCursors,
  markRead,
  type ReadCursors,
} from './conversation-list-state'
import { ThreadView } from './thread-view'

export function ChatPage() {
  const { t } = useLanguage()
  const navigate = useNavigate()
  const location = useLocation()
  const { roomId } = useParams<{ roomId?: string }>()
  const { data, isLoading } = useWorkrooms()
  // v88 P5-A: the task-detail page's "Giao lại việc này" hands the old brief over as
  // router navigation state (avoids URL-length limits a query param would hit on a
  // long brief) — read once on arrival, same one-shot-seed posture as the assistant
  // thread's `?ask=` param.
  const assignSeed = (location.state as { assignSeed?: string } | null)?.assignSeed
  // Clear the seed from history state after the first mount consumes it, so a browser
  // Back to this entry (or a route remount) never re-stomps a draft the user has since
  // edited. `initialBrief` is mount-only, so consuming it once is enough.
  useEffect(() => {
    if (assignSeed) navigate(location.pathname, { replace: true, state: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on arrival
  }, [])
  // Lazily read once: localStorage is synchronous and this is the pane's first paint.
  const [cursors, setCursors] = useState<ReadCursors>(() => loadReadCursors())

  const rooms = useMemo(() => data?.rooms ?? [], [data])
  const conversations = useMemo(() => buildConversations(rooms, cursors), [rooms, cursors])

  // No room in the URL → the overview thread, which is the one room that always exists.
  const activeId = roomId ?? OVERVIEW_ROOM_ID
  const active = conversations.find((c) => c.id === activeId)

  const onRead = useCallback((room: string, seq: number) => {
    // markRead returns the SAME map when the cursor would move backwards, so this
    // setState is a no-op re-render rather than a loop with the thread's effect.
    setCursors((prev) => markRead(prev, room, seq))
  }, [])

  const onSelect = useCallback(
    (id: string) => {
      navigate(id === OVERVIEW_ROOM_ID ? '/chat' : `/chat/${encodeURIComponent(id)}`)
    },
    [navigate],
  )

  const isAssistant = activeId === ASSISTANT_CONVERSATION_ID
  const title = active?.isAssistant
    ? t('chat.assistantRoom')
    : (active?.title ?? t('chat.overviewRoom'))

  // On a phone the hub is two screens, the way a chat app works: the URL alone says
  // which one is showing (no room → list, room → thread). Keeping it in the URL rather
  // than component state means Back works and a deep link opens the thread directly.
  const showsThread = roomId != null

  return (
    <div className={`chat-hub${showsThread ? ' shows-thread' : ' shows-list'}`}>
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={onSelect}
        loading={isLoading}
      />

      <div className="chat-main">
        <button
          type="button"
          className="chat-back"
          onClick={() => navigate('/chat')}
        >
          ← {t('chat.backToList')}
        </button>
        {isAssistant ? (
          <AssistantThread title={title} />
        ) : (
          <ThreadView roomId={activeId} title={title} onRead={onRead} />
        )}

        {!isAssistant ? (
          <AssignComposer
            activeRoom={activeId === OVERVIEW_ROOM_ID ? null : activeId}
            initialBrief={activeId === OVERVIEW_ROOM_ID ? assignSeed : undefined}
          />
        ) : null}
      </div>

      {/* Fleet-wide, not room-scoped: what blocks an agent needs the CEO's attention
          whichever conversation happens to be open. */}
      <PendingPane />
    </div>
  )
}
