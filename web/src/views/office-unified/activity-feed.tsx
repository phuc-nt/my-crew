// Live activity feed (v16): icon + status color per event kind, agent chip in the
// staffer's personal color — the "nhiều thông tin hơn" pass over the v15 text-only
// strip. Colors ride the role-split tokens via CSS classes (no new hex here).
// Receives messages as props — the unified screen owns the stream(s).
import { useEffect, useRef } from 'react'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import type { OfficeMessage } from '../../types'
import { agentColor } from '../office-3d/desk-colors'
import { kindLabel, messageLine } from '../office-shared/office-message-line'

//: The feed shows the tail only — full history lives in the timeline tab.
const FEED_TAIL = 40

const KIND_ICON: Record<string, string> = {
  ceo: '🗣', assignment: '📋', step_status: '⚙', handoff: '✅',
  milestone: '🚩', consult: '💬', review: '🔍',
}

// Status flavor → CSS suffix (token-colored in App.css). Derived from the same body
// fields messageLine renders — one vocabulary, presentation-only.
export function feedStatusClass(m: OfficeMessage): string {
  const b = m.body
  if (m.kind === 'handoff') return 'ok'
  if (m.kind === 'review') return b.verdict === 'passed' ? 'ok' : 'danger'
  if (m.kind === 'step_status') {
    if (b.status === 'failed') return 'danger'
    if (b.phase === 'nho-tro-giup') return 'pending'
    return 'warn' // started/working flavors
  }
  if (m.kind === 'milestone') return b.milestone === 'done' ? 'ok' : 'neutral'
  return 'neutral'
}

interface ActivityFeedProps {
  messages: OfficeMessage[]
  connected: boolean
  errored: boolean
}

export function ActivityFeed({ messages, connected, errored }: ActivityFeedProps) {
  const { t } = useLanguage()
  const listRef = useRef<HTMLUListElement>(null)
  const tail = messages.slice(-FEED_TAIL)

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length])

  return (
    <aside className="office-unified-feed" aria-label={t('activityFeed.ariaLabel')}>
      <p className="office-zone-title">
        {errored
          ? t('activityFeed.disconnected')
          : connected
            ? t('activityFeed.connected')
            : t('activityFeed.connecting')}
      </p>
      {tail.length === 0 && !errored && <EmptyState>{t('activityFeed.empty')}</EmptyState>}
      <ul className="office-room-log office-unified-log" ref={listRef}>
        {tail.map((m) => {
          const who = m.body.assigned_to ?? m.author
          return (
            <li key={m.seq} className={`office-room-entry office-feed-${feedStatusClass(m)}`}>
              <span className="office-feed-icon" aria-hidden>{KIND_ICON[m.kind] ?? '•'}</span>
              <span className="office-room-kind">{kindLabel(m.kind, t)}</span>
              <span className="office-feed-agent" style={{ color: agentColor(who) }}>{who}</span>
              <p className="office-room-text">{messageLine(m, t)}</p>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
