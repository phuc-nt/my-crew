// Left pane: the conversation rows. Presentation only — every ordering/unread rule
// lives in conversation-list-state.ts so it can be tested without a DOM.
import type { UiKey } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'
import type { Conversation } from './conversation-list-state'
import { UNKNOWN_UNREAD } from './conversation-list-state'
import { shortTitle } from './conversation-title'

const STATUS_KEY: Record<string, UiKey> = {
  'dang-chay': 'chat.roomStatus.running',
  ket: 'chat.roomStatus.blocked',
  xong: 'chat.roomStatus.done',
}

interface Props {
  conversations: readonly Conversation[]
  activeId: string
  onSelect: (id: string) => void
  loading?: boolean
}

export function ConversationList({ conversations, activeId, onSelect, loading }: Props) {
  const { t } = useLanguage()

  return (
    <nav className="chat-conversations" aria-label={t('chat.conversationsLabel')}>
      {loading && conversations.length <= 1 ? (
        <p className="chat-conversations-empty">{t('chat.loadingRooms')}</p>
      ) : null}
      <ul className="chat-conversation-list">
        {conversations.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              className={`chat-conversation${c.id === activeId ? ' is-active' : ''}`}
              aria-current={c.id === activeId ? 'true' : undefined}
              onClick={() => onSelect(c.id)}
            >
              <span className="chat-conversation-title">
                {/* Real titles are the CEO's raw brief (median 120 chars) — cut here so
                    the row stays one readable line; the full text is the thread's own. */}
                {c.isAssistant ? `💬 ${t('chat.assistantRoom')}` : shortTitle(c.title)}
              </span>
              <span className="chat-conversation-meta">
                {c.status ? t(STATUS_KEY[c.status] ?? 'chat.roomStatus.running') : null}
              </span>
              {/* A room never opened has no knowable count (last_seq is office-wide), so
                  it shows a dot; a room with a real delta shows the number. */}
              {c.unread === UNKNOWN_UNREAD ? (
                <span className="chat-unread is-dot" aria-label={t('chat.unreadUnknown')} />
              ) : c.unread > 0 ? (
                <span className="chat-unread" aria-label={t('chat.unreadCount', { n: c.unread })}>
                  {c.unread > 99 ? '99+' : c.unread}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
