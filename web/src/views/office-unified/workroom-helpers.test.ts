// v16 pure helpers: roster filter (ring computed over VISIBLE list) + feed status class.
import { expect, test } from 'vitest'
import { DELIVERED_STEP_TYPES, type OfficeMessage } from '../../types'
import { shouldShowBubble } from '../office-3d/agent-office-state'
import { visibleDesks } from '../office-3d/office-canvas'
import { feedStatusClass, matchesFilter } from './activity-feed'
import { maxSeqOf } from './artifact-panel'

function msg(kind: OfficeMessage['kind'], body: OfficeMessage['body']): OfficeMessage {
  return { seq: 1, ts: 't', author: 'x', source_room_id: 't1', kind, body }
}

test('visibleDesks filters ghosts and keeps order; null roster = no filtering', () => {
  expect(visibleDesks(['a', 'ghost', 'b'], ['a', 'b', 'c'])).toEqual(['a', 'b'])
  expect(visibleDesks(['a', 'ghost'], null)).toEqual(['a', 'ghost'])
})

test('feedStatusClass maps kinds/statuses onto token classes', () => {
  expect(feedStatusClass(msg('handoff', {}))).toBe('ok')
  expect(feedStatusClass(msg('review', { verdict: 'passed' }))).toBe('ok')
  expect(feedStatusClass(msg('review', { verdict: 'needs_rework' }))).toBe('danger')
  expect(feedStatusClass(msg('step_status', { status: 'failed' }))).toBe('danger')
  expect(feedStatusClass(msg('step_status', { status: 'started', phase: 'nho-tro-giup' }))).toBe('pending')
  expect(feedStatusClass(msg('step_status', { status: 'started' }))).toBe('warn')
  expect(feedStatusClass(msg('milestone', { milestone: 'done' }))).toBe('ok')
  expect(feedStatusClass(msg('ceo', {}))).toBe('neutral')
})

test('maxSeqOf picks the highest seq among the given kinds only', () => {
  const msgs = [
    msg('handoff', {}), // seq 1 (msg helper fixes seq=1)
    { seq: 9, ts: 't', author: 'x', source_room_id: 't1', kind: 'review' as const, body: {} },
    { seq: 20, ts: 't', author: 'x', source_room_id: 't1', kind: 'ceo' as const, body: {} },
  ]
  // ceo (seq 20) is not counted; review (9) wins over handoff (1)
  expect(maxSeqOf(msgs, ['handoff', 'review'])).toBe(9)
  expect(maxSeqOf(msgs, ['assignment'])).toBe(0)
})

test('a done sprint step counts as delivered work, like work/rework', () => {
  // Mirror of the server's routes_outputs._DELIVERED_TYPES — sprint used to be
  // filtered out here, hiding its artifact from the Kết quả column entirely.
  expect(DELIVERED_STEP_TYPES.has('sprint')).toBe(true)
  expect(DELIVERED_STEP_TYPES.has('work')).toBe(true)
  expect(DELIVERED_STEP_TYPES.has('rework')).toBe(true)
  expect(DELIVERED_STEP_TYPES.has('review')).toBe(false)
})

test('the Bước filter keeps in-step activity ticks, not just lifecycle events', () => {
  expect(matchesFilter(msg('step_status', {}), 'step')).toBe(true)
  expect(matchesFilter(msg('step_activity', { tool: 'web_search', count: 2 }), 'step')).toBe(true)
  expect(matchesFilter(msg('handoff', {}), 'step')).toBe(false)
  expect(matchesFilter(msg('step_activity', {}), 'external')).toBe(false)
})

test('shouldShowBubble: only running/consulting desks speak (v17 Q4)', () => {
  const base = {
    id: 'a', taskTitle: 'T', stepTitle: 'S', phase: null, attemptId: null,
    consultWith: null, lastVerdict: null, picTasks: new Set<string>(),
    concurrentSteps: 0, deepTeamActive: false,
  }
  expect(shouldShowBubble({ ...base, state: 'working' })).toBe(true)
  expect(shouldShowBubble({ ...base, state: 'assigned' })).toBe(true)
  expect(shouldShowBubble({ ...base, state: 'done' })).toBe(false)
  expect(shouldShowBubble({ ...base, state: 'idle' })).toBe(false)
  expect(shouldShowBubble({ ...base, state: 'done', consultWith: 'b' })).toBe(true)
})
