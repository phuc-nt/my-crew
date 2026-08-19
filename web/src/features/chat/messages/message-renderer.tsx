// One thread item → one chat row. Deliberately thin: the event→text vocabulary is the
// SHARED `office-message-line` module, so a line reads identically in the chat thread,
// the activity feed, and the timeline. This file only adds what chat needs on top —
// bubble alignment, the collapsed step block, and the per-kind tone.
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useLanguage } from '../../../i18n/language-context'
import type { OfficeMessage } from '../../../types'
import { kindLabel, messageLine } from '../../shared/office-message-line'
import { markdownComponents } from '../../shared/artifact-viewer'
import type { ThreadItem } from '../chat-state'
import { isClamped, isDeliverable, milestoneText } from './milestone-presentation'
import { StepBlockCard } from './step-block-card'

/** `ceo` is the reader's own message — the only kind drawn as a right-aligned bubble. */
function isOwn(item: ThreadItem): boolean {
  return item.kind === 'ceo'
}

/** Re-materialize the OfficeMessage shape `messageLine` expects from a folded item. */
function asMessage(item: ThreadItem): OfficeMessage {
  return {
    seq: item.seq,
    ts: item.ts,
    author: item.author,
    kind: item.kind,
    body: item.body,
    source_room_id: '',
  }
}

function timeOf(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? '' : d.toTimeString().slice(0, 5)
}

/**
 * The row's text. Mostly the shared vocabulary; `milestone` is the one kind the chat
 * thread words differently (see milestone-presentation.ts for why, with real bodies).
 */
function textOf(item: ThreadItem, t: Parameters<typeof messageLine>[1]): string {
  if (item.kind === 'milestone') return milestoneText(item.body)
  return messageLine(asMessage(item), t)
}

/** Danger for anything the CEO must act on, ok for progress that landed. */
function toneOf(item: ThreadItem): string {
  if (item.kind === 'review' && item.body.verdict !== 'passed') return ' is-danger'
  if (item.status === 'failed') return ' is-danger'
  if (item.kind === 'milestone') return isDeliverable(item.body) ? ' is-ok' : ''
  if (item.kind === 'handoff') return ' is-ok'
  return ''
}

export function MessageRow({ item }: { item: ThreadItem }) {
  const { t } = useLanguage()

  // A run of steps for one task is one card carrying its count, not N near-identical rows.
  if (item.kind === 'step_status' && (item.stepCount ?? 1) > 1) {
    return <StepBlockCard item={item} />
  }

  return (
    <li className={`chat-row${isOwn(item) ? ' is-own' : ''}${toneOf(item)}`}>
      <div className="chat-bubble">
        {!isOwn(item) ? (
          <p className="chat-row-head">
            <span className="chat-author">{item.author}</span>
            <span className="chat-kind">{kindLabel(item.kind, t)}</span>
          </p>
        ) : null}
        {isDeliverable(item.body) ? (
          // A `done` milestone IS the deliverable, and on real data those bodies are
          // markdown documents — headings, bold, GFM pipe tables (measured in room
          // 847cefe9b088: a cost comparison table). Rendered as plain text they read as
          // literal `**` and `|---|`. Same renderer and same safety overrides as the
          // artifact drawer (no raw HTML, no remote <img>), which is already in the entry
          // bundle via Outputs, so this costs no additional bytes.
          <div className="chat-row-text is-result is-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {textOf(item, t)}
            </ReactMarkdown>
          </div>
        ) : (
          <p className={`chat-row-text${
            item.kind === 'milestone' && isClamped(item.body) ? ' is-clamped' : ''}`}>
            {textOf(item, t)}
          </p>
        )}
        {/* A retrying gateway emits the same line over and over; the reducer folds those
            into one row and this is the only place the count is surfaced. */}
        {(item.repeatCount ?? 1) > 1 && (
          <span className="chat-row-repeat">{t('chat.repeatCount', { n: item.repeatCount ?? 1 })}</span>
        )}
        <time className="chat-row-time" dateTime={item.ts}>{timeOf(item.ts)}</time>
      </div>
    </li>
  )
}
