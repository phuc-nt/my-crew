// Table tests for the chat thread reducer. Mirrors agent-office-state.test.ts's style:
// the reducer is pure, so every rule is pinned as data → expected state.
import { describe, expect, test } from 'vitest'
import type { OfficeMessage } from '../../types'
import {
  applyEvent,
  emptyThread,
  OVERVIEW_ROOM_ID,
  reduceThread,
  unreadFor,
  type UnreadInput,
} from './chat-state'

function msg(
  seq: number,
  kind: OfficeMessage['kind'],
  body: OfficeMessage['body'] = {},
  opts: { author?: string; src?: string; ts?: string } = {},
): OfficeMessage {
  return {
    seq,
    ts: opts.ts ?? `2026-08-18T10:00:${String(seq).padStart(2, '0')}Z`,
    author: opts.author ?? 'coordinator',
    kind,
    body,
    source_room_id: opts.src ?? 'room-a',
  }
}

describe('thread item mapping', () => {
  test('a ceo message becomes one chat bubble carrying its text', () => {
    const t = reduceThread([msg(1, 'ceo', { text: 'làm báo cáo tuần' })])
    expect(t.items).toHaveLength(1)
    expect(t.items[0]).toMatchObject({ kind: 'ceo', seq: 1, text: 'làm báo cáo tuần' })
  })

  test('each renderable kind produces exactly one item, in seq order', () => {
    const t = reduceThread([
      msg(1, 'ceo', { text: 'x' }),
      msg(2, 'assignment', { task_title: 'Báo cáo', pic: 'tro-ly-pm', step_count: 3 }),
      msg(3, 'handoff', { step_title: 'Thu thập', assigned_to: 'content' }),
      msg(4, 'review', { verdict: 'passed', criteria_passed: 3, criteria_total: 3 }),
      msg(5, 'milestone', { milestone: 'done', task_title: 'Báo cáo' }),
      msg(6, 'consult', { from: 'content', to: 'tro-ly-pm', question_summary: 'hỏi' }),
      msg(7, 'external_action', { tool: 'telegram', outcome: 'sent' }),
    ])
    expect(t.items.map((i) => [i.seq, i.kind])).toEqual([
      [1, 'ceo'],
      [2, 'assignment'],
      [3, 'handoff'],
      [4, 'review'],
      [5, 'milestone'],
      [6, 'consult'],
      [7, 'external_action'],
    ])
  })

  test('events arriving out of order are placed by seq, not arrival order', () => {
    const t = reduceThread([msg(3, 'ceo', { text: 'ba' }), msg(1, 'ceo', { text: 'một' })])
    expect(t.items.map((i) => i.seq)).toEqual([1, 3])
  })

  test('a replayed seq is ignored — reconnect must not duplicate the thread', () => {
    // The SSE hook replays from the last seq on reconnect; dedup lives here so every
    // consumer of the reducer inherits it.
    const first = reduceThread([msg(1, 'ceo', { text: 'x' }), msg(2, 'handoff', {})])
    const again = applyEvent(first, msg(2, 'handoff', {}))
    expect(again.items.map((i) => i.seq)).toEqual([1, 2])
    expect(again).toBe(first) // unchanged identity → no re-render
  })
})

describe('step_status collapsing', () => {
  test('a run of step_status events for one task collapses into a single block', () => {
    const t = reduceThread([
      msg(1, 'step_status', { task_title: 'Báo cáo', step_title: 'B1', status: 'started' }),
      msg(2, 'step_status', { task_title: 'Báo cáo', step_title: 'B2', status: 'started' }),
      msg(3, 'step_status', { task_title: 'Báo cáo', step_title: 'B3', status: 'started' }),
    ])
    expect(t.items).toHaveLength(1)
    expect(t.items[0]).toMatchObject({ kind: 'step_status', stepCount: 3 })
    // The block keeps the LATEST step visible — that is the useful one while running.
    expect(t.items[0].stepTitle).toBe('B3')
  })

  test('a different kind between two runs breaks the collapse into two blocks', () => {
    const t = reduceThread([
      msg(1, 'step_status', { task_title: 'T', step_title: 'B1', status: 'started' }),
      msg(2, 'handoff', { step_title: 'B1' }),
      msg(3, 'step_status', { task_title: 'T', step_title: 'B2', status: 'started' }),
    ])
    expect(t.items.map((i) => i.kind)).toEqual(['step_status', 'handoff', 'step_status'])
  })

  test('a failed step is never folded into a running block — it must stay visible', () => {
    // `failed` is the only terminal status the backend emits (there is no 'completed';
    // completion arrives as the `handoff` kind), so hiding it inside a count loses the
    // one status a CEO has to act on.
    const t = reduceThread([
      msg(1, 'step_status', { task_title: 'T', step_title: 'B1', status: 'started' }),
      msg(2, 'step_status', { task_title: 'T', step_title: 'B2', status: 'failed' }),
    ])
    expect(t.items.map((i) => [i.kind, i.status])).toEqual([
      ['step_status', 'started'],
      ['step_status', 'failed'],
    ])
  })

  test('a handoff after a run of steps survives — it is not absorbed by the block', () => {
    // Regression: the collapse guard only checked the PREVIOUS item's kind, so a handoff
    // (and review) following steps of the same task was folded into the block and
    // disappeared. Found by replaying a real 121-event room through the reducer.
    const t = reduceThread([
      msg(1, 'step_status', { task_title: 'T', step_title: 'B1', status: 'started' }),
      msg(2, 'step_status', { task_title: 'T', step_title: 'B2', status: 'started' }),
      msg(3, 'handoff', { task_title: 'T', step_title: 'B2', assigned_to: 'content' }),
      msg(4, 'review', { task_title: 'T', verdict: 'passed' }),
    ])
    expect(t.items.map((i) => i.kind)).toEqual(['step_status', 'handoff', 'review'])
    expect(t.items[0].stepCount).toBe(2)
  })

  test('steps of two different tasks do not collapse together', () => {
    const t = reduceThread([
      msg(1, 'step_status', { task_title: 'T1', step_title: 'B1', status: 'started' }),
      msg(2, 'step_status', { task_title: 'T2', step_title: 'B1', status: 'started' }),
    ])
    expect(t.items).toHaveLength(2)
  })
})

describe('step_activity is ephemeral', () => {
  test('step_activity never enters the thread history', () => {
    const t = reduceThread([
      msg(1, 'ceo', { text: 'x' }),
      msg(2, 'step_activity', { tool: 'web_search', count: 3, agent: 'content' }),
    ])
    expect(t.items.map((i) => i.kind)).toEqual(['ceo'])
  })

  test('the newest step_activity replaces the previous one instead of stacking', () => {
    const t = reduceThread([
      msg(1, 'step_activity', { task: 'T', step: 'B1', tool: 'web_search', count: 1 }),
      msg(2, 'step_activity', { task: 'T', step: 'B1', tool: 'web_search', count: 3 }),
    ])
    expect(t.activities).toHaveLength(1)
    expect(t.activities[0]).toMatchObject({ tool: 'web_search', count: 3 })
  })

  test('any non-activity event for that step clears its activity line', () => {
    // The line means "happening right now"; once a real event lands the step moved on.
    const t = reduceThread([
      msg(1, 'step_activity', { task: 'T', step: 'B1', tool: 'web_search', count: 1 }),
      msg(2, 'handoff', { task_title: 'T', step_title: 'B1' }),
    ])
    expect(t.activities).toEqual([])
  })

  test('two concurrent tasks keep separate activity lines, keyed by task+step', () => {
    // Real data: the `office` overview room carries step_activity from 3 distinct tasks
    // at once. A single shared line would let one task erase the other's progress.
    const t = reduceThread(
      [
        msg(1, 'step_activity', { task: 'T1', step: 'B1', tool: 'web_search', count: 2 }),
        msg(2, 'step_activity', { task: 'T2', step: 'B9', tool: 'read_file', count: 5 }),
      ],
      OVERVIEW_ROOM_ID,
    )
    expect(t.activities).toHaveLength(2)
    expect(t.activities.map((a) => [a.task, a.tool, a.count])).toEqual([
      ['T1', 'web_search', 2],
      ['T2', 'read_file', 5],
    ])
  })

  test('a newer activity for the SAME task+step replaces only that line', () => {
    const t = reduceThread(
      [
        msg(1, 'step_activity', { task: 'T1', step: 'B1', tool: 'web_search', count: 2 }),
        msg(2, 'step_activity', { task: 'T2', step: 'B9', tool: 'read_file', count: 5 }),
        msg(3, 'step_activity', { task: 'T1', step: 'B1', tool: 'web_search', count: 7 }),
      ],
      OVERVIEW_ROOM_ID,
    )
    expect(t.activities.map((a) => [a.task, a.count])).toEqual([
      ['T1', 7],
      ['T2', 5],
    ])
  })

  test('a real event for one task clears only that task activity line', () => {
    const t = reduceThread(
      [
        msg(1, 'step_activity', { task: 'T1', step: 'B1', tool: 'web_search', count: 2 }),
        msg(2, 'step_activity', { task: 'T2', step: 'B9', tool: 'read_file', count: 5 }),
        msg(3, 'handoff', { task_title: 'T1', step_title: 'B1' }),
      ],
      OVERVIEW_ROOM_ID,
    )
    expect(t.activities.map((a) => a.task)).toEqual(['T2'])
  })
})

describe('unread counting', () => {
  const base: UnreadInput = { lastSeq: 10, lastReadSeq: 4 }

  test('unread is lastSeq minus lastReadSeq', () => {
    expect(unreadFor(base)).toBe(6)
  })

  test('a room never read shows every event as unread', () => {
    expect(unreadFor({ lastSeq: 3, lastReadSeq: 0 })).toBe(3)
  })

  test('a read cursor ahead of lastSeq clamps to zero, never negative', () => {
    // Happens after the store is pruned/rotated while a stale cursor sits in localStorage.
    expect(unreadFor({ lastSeq: 2, lastReadSeq: 9 })).toBe(0)
  })

  test('an empty room is not unread', () => {
    expect(unreadFor({ lastSeq: 0, lastReadSeq: 0 })).toBe(0)
  })
})

describe('live attribution by source_room_id', () => {
  test('an event bumps the room named by source_room_id', () => {
    const t = applyEvent(emptyThread('room-a'), msg(5, 'handoff', {}, { src: 'room-a' }))
    expect(t.lastSeq).toBe(5)
  })

  test('an event from another room is ignored by this room thread', () => {
    const t = applyEvent(emptyThread('room-a'), msg(5, 'handoff', {}, { src: 'room-b' }))
    expect(t.items).toHaveLength(0)
    expect(t.lastSeq).toBe(0)
  })

  test('an event whose source is the overview room cannot be attributed to a workroom', () => {
    // Legacy mirrored rows (written before the provenance column existed) all report
    // 'office'. They are real events but unattributable, so a workroom thread must not
    // claim them — otherwise every historical event would land in the overview thread.
    const t = applyEvent(emptyThread('room-a'), msg(5, 'handoff', {}, { src: 'office' }))
    expect(t.items).toHaveLength(0)
  })
})

describe('collapsing an identical repeated event', () => {
  // Measured on the live overview room: the last 200 events were 200 copies of the SAME
  // line — `coordinator → telegram:5248565986 · skipped`, a gateway retrying. Without a
  // fold the whole thread is that one line 200 times and every milestone, handoff and
  // assignment is pushed out of the tail entirely. The office activity feed already
  // collapses adjacent repeats; the chat thread must too.
  function gateway(seq: number): OfficeMessage {
    return msg(seq, 'external_action', {
      actor: 'coordinator', tool: 'telegram:5248565986', outcome: 'skipped', detail: '5248565986',
    })
  }

  test('200 identical gateway rows fold into one row carrying the count', () => {
    const t = reduceThread(Array.from({ length: 200 }, (_, i) => gateway(i + 1)))
    expect(t.items).toHaveLength(1)
    expect(t.items[0].repeatCount).toBe(200)
    expect(t.items[0].seq).toBe(200) // addressed by its newest event
  })

  test('a real event between two repeats keeps chronology — no merging across it', () => {
    const t = reduceThread([
      gateway(1), gateway(2),
      msg(3, 'milestone', { milestone: 'done', task_title: 'Báo cáo' }),
      gateway(4), gateway(5), gateway(6),
    ])
    expect(t.items.map((i) => [i.kind, i.repeatCount ?? 1])).toEqual([
      ['external_action', 2],
      ['milestone', 1],
      ['external_action', 3],
    ])
  })

  test('a different outcome is a different line and does not fold in', () => {
    const t = reduceThread([
      gateway(1),
      msg(2, 'external_action', {
        actor: 'coordinator', tool: 'telegram:5248565986', outcome: 'allow', detail: '5248565986',
      }),
    ])
    expect(t.items).toHaveLength(2)
  })

  test('a different author does not fold in even with an identical body', () => {
    const t = reduceThread([
      gateway(1),
      msg(2, 'external_action', {
        actor: 'coordinator', tool: 'telegram:5248565986', outcome: 'skipped', detail: '5248565986',
      }, { author: 'content' }),
    ])
    expect(t.items).toHaveLength(2)
  })

  test('two milestone flavors carrying identical text fold into one row', () => {
    // Live room 8251ebc8c8c0 printed the same 501-char "KHÔNG LÀM ĐƯỢC" wall twice, one
    // second apart, as `done` then `gave_up`. The bodies differ; what the reader sees
    // does not. Folding keys on the rendered line, not on raw body equality.
    const message = "Việc 'Bên mình…' KHÔNG LÀM ĐƯỢC: bước 'Tóm tắt ngắn…'"
    const t = reduceThread([
      msg(1, 'milestone', { task_title: 'T', message, milestone: 'done' }),
      msg(2, 'milestone', { task_title: 'T', message, milestone: 'gave_up' }),
    ])
    expect(t.items).toHaveLength(1)
    expect(t.items[0].repeatCount).toBe(2)
  })

  test('milestones with different text stay separate rows', () => {
    const t = reduceThread([
      msg(1, 'milestone', { task_title: 'T', message: 'Đội đã nhận việc', milestone: 'received' }),
      msg(2, 'milestone', { task_title: 'T', message: 'Xong rồi', milestone: 'done' }),
    ])
    expect(t.items).toHaveLength(2)
  })

  test('two distinct ceo messages never fold, however close together', () => {
    const t = reduceThread([msg(1, 'ceo', { text: 'a' }), msg(2, 'ceo', { text: 'b' })])
    expect(t.items).toHaveLength(2)
  })

  test('the step-block fold still wins for step_status — counts do not double up', () => {
    const t = reduceThread([
      msg(1, 'step_status', { task_title: 'T', step_title: 's1', status: 'started' }),
      msg(2, 'step_status', { task_title: 'T', step_title: 's2', status: 'started' }),
    ])
    expect(t.items).toHaveLength(1)
    expect(t.items[0].stepCount).toBe(2)
    expect(t.items[0].repeatCount ?? 1).toBe(1)
  })
})
