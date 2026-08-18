// SSE → query invalidation.
//
// The office room stream is the app's push channel: when the backend does something,
// a room event is the first place it shows up. This module maps an event kind onto
// the query slices that event could have changed, so a live stream keeps every screen
// current without any screen polling.
//
// It is deliberately a pure table (no QueryClient import) so the mapping can be tested
// as data — a kind that quietly stops invalidating a slice is a screen that silently
// stops updating, which no rendering test would catch.
import type { QueryClient } from '@tanstack/react-query'
import type { OfficeEventKind } from '../../types'
import { queryKeys } from './query-keys'

type QueryKey = readonly unknown[]

/** Mirrors `office_event_projection.VALID_KINDS` on the server. */
export const OFFICE_EVENT_KINDS = [
  'ceo',
  'assignment',
  'step_status',
  'handoff',
  'milestone',
  'consult',
  'review',
  'external_action',
  'step_activity',
] as const satisfies readonly OfficeEventKind[]

/** Kinds that mean task state moved — the board and the outputs list can both differ. */
const WORK_PROGRESS_KINDS: ReadonlySet<OfficeEventKind> = new Set([
  'assignment',
  'milestone',
  'review',
  'step_status',
  'handoff',
])

export function invalidationKeysFor(kind: OfficeEventKind): QueryKey[] {
  // Any event in any room advances that room's `last_seq`, which is what the unread
  // badge subtracts against — so the workroom list is stale after every single kind.
  const keys: QueryKey[] = [queryKeys.office.workrooms()]
  if (WORK_PROGRESS_KINDS.has(kind)) {
    keys.push(queryKeys.tasks.board(), queryKeys.outputs.list())
  }
  if (kind === 'external_action') keys.push(queryKeys.approvals.pending())
  if (kind === 'consult') keys.push(queryKeys.clarify.pending())
  return keys
}

/** Apply one event's invalidations. Called from the stream subscriber. */
export function applyInvalidation(client: QueryClient, kind: OfficeEventKind): void {
  for (const queryKey of invalidationKeysFor(kind)) {
    void client.invalidateQueries({ queryKey })
  }
}
