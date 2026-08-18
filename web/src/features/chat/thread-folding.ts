// When two adjacent events collapse into one row.
//
// These are pure predicates over (previous row, incoming event) — no state, no React.
// They live apart from the reducer because they are the rules the thread's readability
// depends on, each one written against a defect measured on real fleet data, and they
// need to be reviewable and testable without the reducer's bookkeeping around them.
import type { OfficeEventKind, OfficeMessage } from '../../types'
import type { ThreadItem } from './chat-state'

/**
 * Can `msg` extend the collapsed `step_status` block that `prev` represents?
 *
 * Only a running step folds: 'failed' is the one status a CEO must act on, so it always
 * gets its own row. Blocks are per-task so two concurrent tasks' steps never merge.
 */
export function extendsStepBlock(prev: ThreadItem | undefined, msg: OfficeMessage): boolean {
  // BOTH sides must be step_status: without the msg check, a `handoff`/`review` landing
  // after a run of steps was absorbed into the block and vanished from the thread —
  // exactly the events a CEO needs most (measured on a real 121-event room: handoff and
  // review were missing entirely until this guard was added).
  if (!prev || prev.kind !== 'step_status' || msg.kind !== 'step_status') return false
  if (prev.status === 'failed' || msg.body.status === 'failed') return false
  return prev.body.task_title === msg.body.task_title
}

/**
 * Identity of a row for repeat-collapsing: same author, same kind, same rendered body.
 *
 * Measured on the live overview room: its whole 200-event tail was 200 copies of one
 * gateway line (`coordinator → telegram:… · skipped`, a retry loop). Left unfolded that
 * single line IS the thread and every milestone/handoff/assignment falls out of the tail.
 * The office activity feed collapses adjacent repeats for the same reason; this is the
 * chat thread's version of that rule, applied to the reduced state rather than the view
 * so the fold survives the tail slice.
 */
function repeatKey(author: string, kind: OfficeEventKind, body: OfficeMessage['body']): string {
  // Keyed on what the reader SEES, not on raw body equality. Measured in room
  // 8251ebc8c8c0: a `done` and a `gave_up` milestone one second apart carried the SAME
  // 501-char message and differed only in the `milestone` field — two events by body,
  // one wall of text on screen, printed twice. The fields listed here are the ones that
  // reach the rendered line for each kind (see office-message-line.ts / the milestone
  // wording in messages/milestone-presentation.ts).
  const b = body
  const rendered = JSON.stringify([
    b.text, b.message, b.task_title, b.step_title, b.summary, b.status, b.phase,
    b.actor, b.tool, b.detail, b.outcome, b.verdict, b.from, b.to,
    b.question_summary, b.answer_summary,
  ])
  return `${author}\u0000${kind}\u0000${rendered}`
}

/**
 * Can `msg` fold into `prev` as another occurrence of the same line?
 *
 * `ceo` is excluded on purpose: two identical messages the CEO actually typed are two
 * real messages, and hiding the second would misreport what was sent.
 */
export function extendsRepeat(prev: ThreadItem | undefined, msg: OfficeMessage): boolean {
  if (!prev || msg.kind === 'ceo' || prev.kind === 'ceo') return false
  return repeatKey(prev.author, prev.kind, prev.body) === repeatKey(msg.author, msg.kind, msg.body)
}
