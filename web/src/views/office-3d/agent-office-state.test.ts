// Unit tests for the pure event → desk-state reducer. No Canvas, no r3f — this is the state
// machine the 3D scene AND the 2D fallback table both read from.
//
// Event shapes here match what the backend ACTUALLY emits (grep `tick_actions.py`'s
// `reserve_and_spawn` and `team_step_runner.py`'s `_append_step_event`): `step_status` carries
// `assigned_to` in the body and `author: "coordinator"` for `started`, `author: <agent>` for
// `failed`; `handoff` carries `author: <agent>` (== `assigned_to`). There is no `completed`/
// `done`/`in_progress` status string in production — a completed step is signaled by the
// `handoff` KIND, not a `step_status` status value.
import { describe, expect, test } from 'vitest'
import type { OfficeMessage } from '../../types'
import { agentIdsInOrder, deriveAgentDesks, derivePendingCounts, shouldShowBubble } from './agent-office-state'

function msg(partial: Partial<OfficeMessage> & Pick<OfficeMessage, 'kind' | 'author'>): OfficeMessage {
  return { seq: 1, ts: 't', body: {}, ...partial }
}

describe('deriveAgentDesks', () => {
  test('an empty stream yields no desks', () => {
    expect(deriveAgentDesks([]).size).toBe(0)
  })

  test('step_status started (ticker-authored, assigned_to names the real worker) moves the ASSIGNEE desk to working, not a "coordinator" desk', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')).toEqual({
      id: 'agent-a',
      state: 'working',
      taskTitle: 'Demo',
      stepTitle: 'draft',
      phase: null,
      attemptId: null,
      consultWith: null,
      lastVerdict: null,
      picTasks: new Set(),
      concurrentSteps: 1,
      deepTeamActive: false,
    })
    expect(desks.has('coordinator')).toBe(false)
  })

  test('a step_status event with no assigned_to updates no desk (defensive, never crashes)', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started' } }),
    ])
    expect(desks.size).toBe(0)
  })

  test('a handoff (worker-authored, done) moves the author desk to done', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
      }),
      msg({
        kind: 'handoff', author: 'agent-a',
        body: { task_title: 'Demo', step_title: 'draft', message: 'xong', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')?.state).toBe('done')
  })

  test('a worker-authored step_status failed shows the error state (dual-lens P1)', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
      }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { task_title: 'Demo', step_title: 'draft', status: 'failed', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')?.state).toBe('error')
  })

  test('a handoff event marks the assignee desk as done and carries task/step titles', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'handoff', author: 'agent-b',
        body: { task_title: 'Demo', step_title: 'review', message: 'xong', assigned_to: 'agent-b' },
      }),
    ])
    expect(desks.get('agent-b')).toEqual({
      id: 'agent-b',
      state: 'done',
      taskTitle: 'Demo',
      stepTitle: 'review',
      phase: null,
      attemptId: null,
      consultWith: null,
      lastVerdict: null,
      picTasks: new Set(),
      concurrentSteps: 0,
      deepTeamActive: false,
    })
  })

  test('a handoff missing assigned_to falls back to author (defensive)', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'handoff', author: 'agent-b', body: { task_title: 'Demo', message: 'xong' } }),
    ])
    expect(desks.get('agent-b')?.state).toBe('done')
  })

  test('milestone and ceo events do not create desks', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'ceo', author: 'ceo', body: { text: 'go' } }),
      msg({ kind: 'milestone', author: 'coordinator', body: { task_title: 'Demo', milestone: 'done' } }),
    ])
    expect(desks.size).toBe(0)
  })

  test('assignment events (task-level, no single assignee) do not create a desk', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'assignment', author: 'coordinator', body: { task_title: 'Demo', step_count: 2, summary: 'a, b' } }),
    ])
    expect(desks.size).toBe(0)
  })

  test('multiple agents each get their own desk, independently tracked', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { task_title: 'T1', step_title: 's1', status: 'started', assigned_to: 'agent-a' },
      }),
      msg({
        kind: 'handoff', author: 'agent-b',
        body: { task_title: 'T2', step_title: 's2', message: 'xong', assigned_to: 'agent-b' },
      }),
    ])
    expect(desks.get('agent-a')?.state).toBe('working')
    expect(desks.get('agent-b')?.state).toBe('done')
  })

  test('a later real event always wins — a started after a handoff moves the desk back to working', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'handoff', author: 'agent-a',
        body: { assigned_to: 'agent-a', message: 'xong' },
      }),
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')?.state).toBe('working')
  })

  test('a phase event (work/self_check/rework) keeps state=working and exposes phase text', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a', task_title: 'Demo', step_title: 'draft' },
      }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'tu-soat', attempt_id: 'att-1' },
      }),
    ])
    const desk = desks.get('agent-a')
    expect(desk?.state).toBe('working')
    expect(desk?.phase).toBe('tu-soat')
    expect(desk?.attemptId).toBe('att-1')
  })

  test('a stale attempt id phase event is dropped (zombie-attempt guard)', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a' },
      }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-1' },
      }),
      // A late-arriving event from a SUPERSEDED attempt (e.g. reconnect-replay
      // reordering) must not overwrite the current attempt's phase.
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-sua', attempt_id: 'att-0' },
      }),
    ])
    const desk = desks.get('agent-a')
    expect(desk?.phase).toBe('dang-lam')
    expect(desk?.attemptId).toBe('att-1')
  })

  test('a fresh dispatch (no attempt_id) after a prior attempt resets phase and adopts the new attempt id', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-sua', attempt_id: 'att-1' },
      }),
      // The ticker's own re-dispatch (retry) carries no attempt_id — it starts a NEW
      // attempt's window, so the OLD phase text must not linger.
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a' },
      }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-2' },
      }),
    ])
    const desk = desks.get('agent-a')
    expect(desk?.phase).toBe('dang-lam')
    expect(desk?.attemptId).toBe('att-2')
  })

  test('a consult event sets consultWith on BOTH the asker and the colleague desks', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a', to: 'agent-b' } }),
    ])
    expect(desks.get('agent-a')?.consultWith).toBe('agent-b')
    expect(desks.get('agent-b')?.consultWith).toBe('agent-a')
  })

  test('a consult event does not change state/taskTitle/stepTitle — advisory only', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
      }),
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a', to: 'agent-b' } }),
    ])
    const desk = desks.get('agent-a')
    expect(desk?.state).toBe('working')
    expect(desk?.taskTitle).toBe('Demo')
    expect(desk?.consultWith).toBe('agent-b')
  })

  test('either desk\'s NEXT event (any kind) clears consultWith on BOTH — event-driven, no timer', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a', to: 'agent-b' } }),
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')?.consultWith).toBeNull()
    // v14: the consulted colleague is released too — an idle colleague may never emit
    // its own event, and with walk-to-consult its avatar would otherwise stand at the
    // meeting point forever (asymmetric clearing was fine when this was only a bubble).
    expect(desks.get('agent-b')?.consultWith).toBeNull()
  })

  test('the symmetric clear only releases a partner still consulting THIS desk', () => {
    const desks = deriveAgentDesks([
      // b's live consult is with c (b→c came after a→b overwrote it) — a moving on
      // must NOT tear down b↔c.
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a', to: 'agent-b' } }),
      msg({ kind: 'consult', author: 'agent-b', body: { from: 'agent-b', to: 'agent-c' } }),
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')?.consultWith).toBeNull()
    expect(desks.get('agent-b')?.consultWith).toBe('agent-c')
    expect(desks.get('agent-c')?.consultWith).toBe('agent-b')
  })

  test('a handoff event also clears a stale consultWith on that desk', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a', to: 'agent-b' } }),
      msg({ kind: 'handoff', author: 'agent-a', body: { assigned_to: 'agent-a', message: 'xong' } }),
    ])
    expect(desks.get('agent-a')?.consultWith).toBeNull()
  })

  test('a consult event with a missing from/to is defensive (updates only the present side)', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a' } }),
    ])
    expect(desks.get('agent-a')?.consultWith).toBeNull()
    expect(desks.has('agent-b')).toBe(false)
  })
})

describe('agentIdsInOrder', () => {
  test('returns distinct agent ids in first-seen order, keyed by assigned_to (never author)', () => {
    const ids = agentIdsInOrder([
      msg({ kind: 'ceo', author: 'ceo' }),
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-b' } }),
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({ kind: 'handoff', author: 'agent-b', body: { message: 'xong', assigned_to: 'agent-b' } }),
    ])
    expect(ids).toEqual(['agent-b', 'agent-a'])
  })

  test('an empty stream yields no agent ids', () => {
    expect(agentIdsInOrder([])).toEqual([])
  })

  test('a consult event contributes both from and to ids', () => {
    const ids = agentIdsInOrder([
      msg({ kind: 'consult', author: 'agent-a', body: { from: 'agent-a', to: 'agent-b' } }),
    ])
    expect(ids).toEqual(['agent-a', 'agent-b'])
  })
})

describe('PIC badge (v15)', () => {
  test('an assignment with pic+task_id badges the PIC desk; milestone done clears it', () => {
    const desks1 = deriveAgentDesks([
      msg({ kind: 'assignment', author: 'coordinator', body: { pic: 'noi-dung', task_id: 't-1', summary: 'x' } }),
    ])
    expect(desks1.get('noi-dung')?.picTasks.has('t-1')).toBe(true)

    const desks2 = deriveAgentDesks([
      msg({ kind: 'assignment', author: 'coordinator', body: { pic: 'noi-dung', task_id: 't-1', summary: 'x' } }),
      msg({ kind: 'milestone', author: 'coordinator', body: { milestone: 'done', task_id: 't-1' } }),
    ])
    expect(desks2.get('noi-dung')?.picTasks.size).toBe(0)
  })

  test('a non-done milestone (received/cost_warn) does NOT clear the badge', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'assignment', author: 'coordinator', body: { pic: 'noi-dung', task_id: 't-1', summary: 'x' } }),
      msg({ kind: 'milestone', author: 'coordinator', body: { milestone: 'received', task_id: 't-1' } }),
    ])
    expect(desks.get('noi-dung')?.picTasks.has('t-1')).toBe(true)
  })

  test('two concurrent tasks: done of one keeps the badge for the other', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'assignment', author: 'coordinator', body: { pic: 'noi-dung', task_id: 't-1', summary: 'x' } }),
      msg({ kind: 'assignment', author: 'coordinator', body: { pic: 'noi-dung', task_id: 't-2', summary: 'y' } }),
      msg({ kind: 'milestone', author: 'coordinator', body: { milestone: 'done', task_id: 't-1' } }),
    ])
    expect(desks.get('noi-dung')?.picTasks.size).toBe(1)
  })

  test('agentIdsInOrder surfaces the PIC desk from the assignment alone (F8)', () => {
    const ids = agentIdsInOrder([
      msg({ kind: 'assignment', author: 'coordinator', body: { pic: 'noi-dung', task_id: 't-1' } }),
    ])
    expect(ids).toEqual(['noi-dung'])
  })
})

// v32: the desk tooltip line is a pure function — the one visual-logic seam testable
// without a WebGL canvas.
import { deskTooltipText } from './agent-desk'

test('deskTooltipText names the state and the current work', () => {
  const base = {
    id: 'a', taskTitle: null, stepTitle: null, phase: null, attemptId: null,
    consultWith: null, picTasks: new Set<string>(),
  }
  expect(deskTooltipText({ ...base, state: 'idle' } as never)).toBe('đang rảnh')
  expect(deskTooltipText({ ...base, state: 'working', stepTitle: 'soạn outline' } as never))
    .toBe('đang làm — soạn outline')
  expect(deskTooltipText({ ...base, state: 'done', taskTitle: 'Bài blog' } as never))
    .toBe('vừa xong một bước — Bài blog')
})

// --- Dual-lens P1: error visual + review verdict capture ---

describe('dual-lens P1: error state + verdict', () => {
  const started = (agent: string) =>
    msg({
      kind: 'step_status', author: 'coordinator',
      body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: agent },
    })
  const failed = (agent: string) =>
    msg({
      kind: 'step_status', author: agent,
      body: { task_title: 'Demo', step_title: 'draft', status: 'failed', assigned_to: agent },
    })

  test('an error desk still speaks (bubble carries the ⚠) and recovers on the next dispatch', () => {
    const errored = deriveAgentDesks([started('a'), failed('a')]).get('a')
    expect(errored?.state).toBe('error')
    expect(shouldShowBubble(errored as never)).toBe(true)
    // next dispatch (retry / new task) clears the error like any other transition
    const recovered = deriveAgentDesks([started('a'), failed('a'), started('a')]).get('a')
    expect(recovered?.state).toBe('working')
  })

  test('a review event stores the closed-enum verdict for the flash layer', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'review', author: 'reviewer', ts: '2026-07-18T09:00:00Z',
        body: {
          task_title: 'Demo', step_title: 'review', verdict: 'needs_rework',
          failure_count: 2, criteria_total: 5, criteria_passed: 3, assigned_to: 'reviewer',
        },
      }),
    ])
    expect(desks.get('reviewer')?.lastVerdict).toEqual({
      verdict: 'needs_rework', failureCount: 2, criteriaTotal: 5, criteriaPassed: 3,
      ts: '2026-07-18T09:00:00Z',
    })
  })

  test('an unknown/blank verdict (server already dropped it) sets nothing', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'review', author: 'r', body: { verdict: '', assigned_to: 'r' } as never }),
    ])
    expect(desks.get('r')?.lastVerdict).toBeNull()
  })
})

// --- v54 P4: concurrentSteps (×N fan-out badge) + deepTeamActive (ghost figure) ---

describe('v54 P4: concurrentSteps fan-out counter', () => {
  test('a fresh desk with no events has concurrentSteps 0', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'consult', author: 'a', body: { from: 'a', to: 'agent-a' } }),
    ])
    expect(desks.get('agent-a')?.concurrentSteps).toBe(0)
  })

  test('one dispatch (started, no attempt_id) sets concurrentSteps to 1 — below the ×N threshold', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a' },
      }),
    ])
    expect(desks.get('agent-a')?.concurrentSteps).toBe(1)
  })

  test('two dispatches to the same agent (parallel fan-out) sets concurrentSteps to 2', () => {
    const desks = deriveAgentDesks([
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a', step_title: 's1' },
      }),
      msg({
        kind: 'step_status', author: 'coordinator',
        body: { status: 'started', assigned_to: 'agent-a', step_title: 's2' },
      }),
    ])
    expect(desks.get('agent-a')?.concurrentSteps).toBe(2)
  })

  test('a handoff resolves one dispatched step — counter decrements back toward 0', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({ kind: 'handoff', author: 'agent-a', body: { assigned_to: 'agent-a', message: 'xong' } }),
    ])
    expect(desks.get('agent-a')?.concurrentSteps).toBe(1)
  })

  test('a failed step also resolves one dispatched step', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({ kind: 'step_status', author: 'agent-a', body: { status: 'failed', assigned_to: 'agent-a' } }),
    ])
    expect(desks.get('agent-a')?.concurrentSteps).toBe(0)
  })

  test('a review verdict (reviewer desk terminal) also resolves one dispatched step', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'reviewer' } }),
      msg({ kind: 'review', author: 'reviewer', body: { verdict: 'passed', assigned_to: 'reviewer' } }),
    ])
    expect(desks.get('reviewer')?.concurrentSteps).toBe(0)
  })

  test('a terminal event with nothing outstanding floors at 0, never negative', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'handoff', author: 'agent-a', body: { assigned_to: 'agent-a', message: 'xong' } }),
    ])
    expect(desks.get('agent-a')?.concurrentSteps).toBe(0)
  })
})

describe('v54 P4: deepTeamActive ghost figure', () => {
  test('a plain phase event (no deep_team) leaves deepTeamActive false', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-1' },
      }),
    ])
    expect(desks.get('agent-a')?.deepTeamActive).toBe(false)
  })

  test('a phase event carrying deep_team: true turns the ghost on for the current attempt', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-1', deep_team: true },
      }),
    ])
    expect(desks.get('agent-a')?.deepTeamActive).toBe(true)
  })

  test('the step resolving (handoff) turns the ghost back off', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-1', deep_team: true },
      }),
      msg({ kind: 'handoff', author: 'agent-a', body: { assigned_to: 'agent-a', message: 'xong' } }),
    ])
    expect(desks.get('agent-a')?.deepTeamActive).toBe(false)
  })

  test('a fresh re-dispatch (new attempt) clears the previous attempt\'s ghost until its own phase event opts in', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-1', deep_team: true },
      }),
      // ticker re-dispatch (retry) — no attempt_id — starts a NEW attempt's window
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
    ])
    expect(desks.get('agent-a')?.deepTeamActive).toBe(false)
  })

  test('a stale attempt\'s deep_team phase event is dropped like any other stale phase event', () => {
    const desks = deriveAgentDesks([
      msg({ kind: 'step_status', author: 'coordinator', body: { status: 'started', assigned_to: 'agent-a' } }),
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-lam', attempt_id: 'att-2' },
      }),
      // late-arriving event from a SUPERSEDED attempt — must not turn the ghost on
      msg({
        kind: 'step_status', author: 'agent-a',
        body: { status: 'started', assigned_to: 'agent-a', phase: 'dang-sua', attempt_id: 'att-1', deep_team: true },
      }),
    ])
    expect(desks.get('agent-a')?.deepTeamActive).toBe(false)
  })
})

describe('v54 P4: derivePendingCounts', () => {
  test('no approvals and no clarify questions yields an empty map (0 pending everywhere)', () => {
    const counts = derivePendingCounts([], [])
    expect(counts.size).toBe(0)
    expect(counts.get('agent-a')).toBeUndefined()
  })

  test('one approval for an agent counts 1', () => {
    const counts = derivePendingCounts([{ agentId: 'agent-a' }], [])
    expect(counts.get('agent-a')).toBe(1)
  })

  test('one clarify question for an agent counts 1', () => {
    const counts = derivePendingCounts([], [{ agent_id: 'agent-a' }])
    expect(counts.get('agent-a')).toBe(1)
  })

  test('approvals and clarify questions for the same agent merge into one count (N >= 2)', () => {
    const counts = derivePendingCounts(
      [{ agentId: 'agent-a' }, { agentId: 'agent-a' }],
      [{ agent_id: 'agent-a' }],
    )
    expect(counts.get('agent-a')).toBe(3)
  })

  test('different agents get independent counts', () => {
    const counts = derivePendingCounts(
      [{ agentId: 'agent-a' }],
      [{ agent_id: 'agent-b' }],
    )
    expect(counts.get('agent-a')).toBe(1)
    expect(counts.get('agent-b')).toBe(1)
  })
})
