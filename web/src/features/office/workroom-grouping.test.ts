// v55 pure rules: recurring-run grouping, status rollup, filter chips + search + the
// active-room force-include (deep-link ?room=<id> must never land on a hidden room).
import { expect, test } from 'vitest'
import type { Workroom } from '../../types'
import { countByStatus, filterWorkroomGroups, groupWorkrooms } from './workroom-grouping'

function room(id: string, title: string, status: Workroom['status'], updated = 't1'): Workroom {
  return { room_id: id, title, task_count: 1, status, updated_at: updated, last_seq: 0 }
}

const WATCH = '[watch:jira-scrum] Có thay đổi'

test('identical titles collapse into one group; distinct titles stay single', () => {
  const groups = groupWorkrooms([
    room('w3', WATCH, 'xong', 't3'), room('a', 'Việc A', 'dang-chay', 't2'),
    room('w2', WATCH, 'xong', 't2'), room('w1', WATCH, 'xong', 't1'),
  ])
  expect(groups.map((g) => [g.title, g.rooms.length])).toEqual([[WATCH, 3], ['Việc A', 1]])
  // Members keep input (newest-first) order.
  expect(groups[0].rooms.map((r) => r.room_id)).toEqual(['w3', 'w2', 'w1'])
})

test('group status rollup: ket beats dang-chay beats xong; updated_at is the max', () => {
  const mixed = groupWorkrooms([
    room('1', 'T', 'xong', 't1'), room('2', 'T', 'dang-chay', 't3'), room('3', 'T', 'ket', 't2'),
  ])[0]
  expect(mixed.status).toBe('ket')
  expect(mixed.updated_at).toBe('t3')
  const running = groupWorkrooms([room('1', 'U', 'xong'), room('2', 'U', 'dang-chay')])[0]
  expect(running.status).toBe('dang-chay')
})

test('countByStatus counts rooms, not groups', () => {
  expect(countByStatus([
    room('1', 'T', 'xong'), room('2', 'T', 'xong'), room('3', 'U', 'ket'),
  ])).toEqual({ 'dang-chay': 0, ket: 1, xong: 2 })
})

test('status filter hides disabled rollups; default-style set shows running + stalled', () => {
  const groups = groupWorkrooms([
    room('a', 'A', 'dang-chay'), room('b', 'B', 'ket'), room('c', 'C', 'xong'),
  ])
  const visible = filterWorkroomGroups(groups, new Set(['dang-chay', 'ket']), '', null)
  expect(visible.map((g) => g.title)).toEqual(['A', 'B'])
})

test('a non-empty search matches by substring and IGNORES the status filter', () => {
  const groups = groupWorkrooms([room('a', 'Soạn slogan', 'dang-chay'), room('c', 'Điều tra GPT', 'xong')])
  const visible = filterWorkroomGroups(groups, new Set(['dang-chay']), 'gpt', null)
  expect(visible.map((g) => g.title)).toEqual(['Điều tra GPT'])
})

test('the active room forces its group visible past both filter and search', () => {
  const groups = groupWorkrooms([room('a', 'A', 'xong'), room('b', 'B', 'dang-chay')])
  const visible = filterWorkroomGroups(groups, new Set(['dang-chay']), 'zzz-no-match', 'a')
  expect(visible.map((g) => g.title)).toEqual(['A'])
})
