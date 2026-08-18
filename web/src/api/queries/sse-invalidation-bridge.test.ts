// The mapping from room-event kind → which query slices go stale. Pure table, so it
// is tested as data: a kind that stops invalidating a slice is a screen that silently
// stops updating on live events, which no rendering test would catch.
import { expect, test } from 'vitest'
import { queryKeys } from './query-keys'
import { invalidationKeysFor, OFFICE_EVENT_KINDS } from './sse-invalidation-bridge'

test('work-progress kinds refresh the board and the outputs list', () => {
  // `handoff` belongs here too: it is the event that delivers a step's result, so the
  // outputs list gains a row and the board's step state moves at the same time.
  for (const kind of ['assignment', 'milestone', 'review', 'step_status', 'handoff'] as const) {
    const keys = invalidationKeysFor(kind)
    expect(keys).toContainEqual(queryKeys.tasks.board())
    expect(keys).toContainEqual(queryKeys.outputs.list())
  }
})

test('an external action refreshes the approvals queue', () => {
  expect(invalidationKeysFor('external_action')).toContainEqual(queryKeys.approvals.pending())
})

test('a consult refreshes the clarify queue', () => {
  expect(invalidationKeysFor('consult')).toContainEqual(queryKeys.clarify.pending())
})

test('every kind refreshes the workroom list so unread counts stay honest', () => {
  // `last_seq` drives the unread badge, so ANY event in ANY room moves it.
  for (const kind of OFFICE_EVENT_KINDS) {
    expect(invalidationKeysFor(kind)).toContainEqual(queryKeys.office.workrooms())
  }
})

test('a ceo message does not refetch the board', () => {
  // Typing in a room is not task state. Invalidating the board here would refetch it
  // on every keystroke-sized message the CEO sends.
  expect(invalidationKeysFor('ceo')).toEqual([queryKeys.office.workrooms()])
})

test('an unmapped kind still refreshes the workroom list and nothing else', () => {
  // `step_activity` is pure telemetry — it carries no task-state change, so invalidating
  // the board on it would refetch on every tool call an agent makes.
  expect(invalidationKeysFor('step_activity')).toEqual([queryKeys.office.workrooms()])
})

test('the kind table covers exactly the backend VALID_KINDS set', () => {
  // Mirrors `office_event_projection.VALID_KINDS`. A kind added on the server without a
  // mapping here would arrive at runtime and invalidate nothing.
  expect([...OFFICE_EVENT_KINDS].sort()).toEqual([
    'assignment',
    'ceo',
    'consult',
    'external_action',
    'handoff',
    'milestone',
    'review',
    'step_activity',
    'step_status',
  ])
})
