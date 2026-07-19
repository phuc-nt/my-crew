// Live activity feed (v16): icon + status color per event kind, agent chip in the
// staffer's personal color — the "nhiều thông tin hơn" pass over the v15 text-only
// strip. Colors ride the role-split tokens via CSS classes (no new hex here).
// Receives messages as props — the unified screen owns the stream(s).
//
// v54 P3: filter chips [Tất cả | Bước | Ra ngoài] — presentation-only over the SAME
// merged-by-seq stream (no re-sort, no re-fetch); "Bước" narrows to step/step_status
// kinds, "Ra ngoài" to external_action (the Action Gateway outcome bridge).
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import type { OfficeMessage } from '../../types'
import { agentColor } from '../office-3d/desk-colors'
import { externalActionTone, kindLabel, messageLine } from '../office-shared/office-message-line'

//: The feed shows the tail only — full history lives in the timeline tab.
const FEED_TAIL = 40

const KIND_ICON: Record<string, string> = {
  ceo: '🗣', assignment: '📋', step_status: '⚙', handoff: '✅',
  milestone: '🚩', consult: '💬', review: '🔍', external_action: '🔗',
}

type FeedFilter = 'all' | 'step' | 'external'

const STEP_KINDS = new Set<OfficeMessage['kind']>(['step_status'])

function matchesFilter(m: OfficeMessage, filter: FeedFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'step') return STEP_KINDS.has(m.kind)
  return m.kind === 'external_action'
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
  if (m.kind === 'external_action') return externalActionTone(b.outcome)
  return 'neutral'
}

interface ActivityFeedProps {
  messages: OfficeMessage[]
  connected: boolean
  errored: boolean
  // v54 P3: clicking a `review` line opens the per-criterion tray in the right column —
  // optional so callers that don't wire the tray (e.g. existing tests) keep rendering
  // review lines as plain text.
  onReviewSelect?: (m: OfficeMessage) => void
}

export function ActivityFeed({ messages, connected, errored, onReviewSelect }: ActivityFeedProps) {
  const { t } = useLanguage()
  const listRef = useRef<HTMLUListElement>(null)
  const [filter, setFilter] = useState<FeedFilter>('all')
  // Filter narrows the already-tailed, already-seq-merged stream — no re-sort (v17
  // ordering contract), no re-fetch (props-only component).
  const tail = messages.slice(-FEED_TAIL).filter((m) => matchesFilter(m, filter))

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length])

  const emptyLabel = filter === 'external'
    ? t('activityFeed.emptyExternal')
    : filter === 'step'
      ? t('activityFeed.emptyStep')
      : t('activityFeed.empty')

  return (
    <aside className="office-unified-feed" aria-label={t('activityFeed.ariaLabel')}>
      <p className="office-zone-title">
        {errored
          ? t('activityFeed.disconnected')
          : connected
            ? t('activityFeed.connected')
            : t('activityFeed.connecting')}
      </p>
      <div className="office-feed-filters" role="group" aria-label={t('activityFeed.filterAriaLabel')}>
        {(['all', 'step', 'external'] as const).map((f) => (
          <Button
            key={f}
            variant="chip"
            aria-pressed={filter === f}
            className={filter === f ? 'chip-active' : undefined}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? t('activityFeed.filterAll')
              : f === 'step' ? t('activityFeed.filterStep')
                : t('activityFeed.filterExternal')}
          </Button>
        ))}
      </div>
      {tail.length === 0 && !errored && <EmptyState>{emptyLabel}</EmptyState>}
      <ul className="office-room-log office-unified-log" ref={listRef}>
        {tail.map((m) => {
          const who = m.body.assigned_to ?? m.author
          const clickableReview = m.kind === 'review' && onReviewSelect
          const text = <p className="office-room-text">{messageLine(m, t)}</p>
          return (
            <li key={m.seq} className={`office-room-entry office-feed-${feedStatusClass(m)}`}>
              <span className="office-feed-icon" aria-hidden>{KIND_ICON[m.kind] ?? '•'}</span>
              <span className="office-room-kind">{kindLabel(m.kind, t)}</span>
              <span className="office-feed-agent" style={{ color: agentColor(who) }}>{who}</span>
              {clickableReview ? (
                <button type="button" className="office-feed-review-line" onClick={() => onReviewSelect(m)}>
                  {text}
                </button>
              ) : text}
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
