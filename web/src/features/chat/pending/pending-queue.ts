// The CEO's "waiting on you" queue: approvals and clarify questions in one list.
//
// Two backends, one reader concern. Both block an agent until the CEO acts, and the
// only thing that matters is which has been waiting longest — so they merge into a
// single time-ordered list rather than two panes the reader has to scan separately.
//
// Pure: the components only render what this returns, so the ordering and expiry rules
// are testable without a query client or a DOM.
import type { ClarifyQuestion, FleetApprovalItem } from '../../../types'

export interface PendingEntry {
  /** Stable across both sources — the two id spaces overlap (both are ints from 1). */
  key: string
  kind: 'approval' | 'question'
  agentId: string
  /** ISO timestamp this item started waiting; drives the ordering. */
  waitingSince: string
  approval?: FleetApprovalItem
  question?: ClarifyQuestion
}

/** Oldest first: the thing that has blocked an agent longest is the thing to do next. */
export function buildPendingQueue(
  approvals: readonly FleetApprovalItem[],
  questions: readonly ClarifyQuestion[],
): PendingEntry[] {
  const entries: PendingEntry[] = [
    ...approvals.map((a): PendingEntry => ({
      key: `approval:${a.agent_id}:${a.id}`,
      kind: 'approval',
      agentId: a.agent_id,
      waitingSince: a.created_at,
      approval: a,
    })),
    ...questions.map((q): PendingEntry => ({
      key: `question:${q.id}`,
      kind: 'question',
      agentId: q.agent_id,
      waitingSince: q.asked_at,
      question: q,
    })),
  ]
  // localeCompare, not Date parsing: these are ISO-8601 strings from the same backend,
  // so lexical order IS chronological order, and an unparseable value can't silently
  // become NaN and scramble the list.
  return entries.sort((a, b) => (a.waitingSince || '').localeCompare(b.waitingSince || ''))
}

/**
 * A question past its expiry is still listed but marked: the backend rejects an answer
 * to it, so presenting it as actionable would send the CEO into a guaranteed 409.
 */
export function isExpired(q: ClarifyQuestion, now: string): boolean {
  return Boolean(q.expires_at) && q.expires_at <= now
}
