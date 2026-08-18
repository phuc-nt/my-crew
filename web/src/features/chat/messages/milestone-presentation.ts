// How a `milestone` event reads in the chat thread.
//
// The shared `officeMessageLine.milestoneLine` renders "{taskTitle}: {message}", which is
// right for the office feed (a one-line index where the task title is the only context).
// In a chat thread it is wrong twice over, both measured on real data:
//   - `message` is self-contained and already opens by restating the task — e.g.
//     "Đội đã nhận việc '<title>' (1 bước)." — so prefixing the title prints it twice,
//     and titles here run to 120 chars.
//   - the thread already shows which room/task it is; the title is not new information.
//
// The `milestone` field is the part that carries meaning and the shared line drops it:
// 'done' holds the actual deliverable (an email, a cost table), while 'received' /
// 'stuck' / 'follow_up' / 'gave_up' are status notices whose text is padding.
import type { OfficeMessage } from '../../../types'

/** Milestone flavors, per the backend's emitters. */
export type MilestoneKey = 'received' | 'stuck' | 'done' | 'gave_up' | 'follow_up'

/**
 * Marker the backend puts in a `done` message when the task did NOT actually deliver.
 * Real example (room 8251ebc8c8c0): milestone='done' whose message reads
 * "Việc '…' KHÔNG LÀM ĐƯỢC: bước '…' — không có người đủ công cụ". The flavor says done;
 * the prose is a failure notice. Flavor alone is therefore not enough to call it a result.
 */
const NOT_DELIVERED = 'KHÔNG LÀM ĐƯỢC'

/**
 * A `done` milestone is the task's deliverable — the one flavor worth reading in full,
 * unless its own text says the work could not be done (see NOT_DELIVERED).
 */
export function isDeliverable(body: OfficeMessage['body']): boolean {
  if (body.milestone !== 'done') return false
  return !(body.message ?? '').includes(NOT_DELIVERED)
}

/**
 * The thread text for a milestone: its message alone, never re-prefixed with the title.
 * Falls back to the shared line's inputs when a body carries no message at all.
 */
export function milestoneText(body: OfficeMessage['body']): string {
  return (body.message ?? '').trim() || (body.task_title ?? '').trim()
}

/**
 * Status milestones (`stuck`, `gave_up`, `received`, `follow_up`) get a clamped bubble.
 *
 * The backend caps `message` at 501 chars, and it caps mid-word — a `stuck` notice
 * renders as a 500-char wall ending "…Google W…". That is a status update, not something
 * to read: what matters is that the task stalled. Only `done` carries a deliverable
 * worth its full height, so only `done` is exempt.
 */
export function isClamped(body: OfficeMessage['body']): boolean {
  return !isDeliverable(body)
}
