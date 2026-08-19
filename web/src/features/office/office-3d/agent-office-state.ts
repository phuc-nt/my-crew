// Pure event → state-machine mapping shared by the 3D scene and the 2D fallback table
// (agent-status-table.tsx). Kept dependency-free (no r3f/Canvas) so it is unit-testable in
// plain jsdom, matching the "SSE-driven only" requirement: this is the single place that
// decides what "idle / assigned / working / done" means for an agent, derived ONLY from the
// office room's OfficeMessage stream (no polling, no local-only state).
//
// v54 P4: three CHEAP 3D desk indicators (CEO decision — no new geometry/animation
// systems). All derivation logic lives HERE (pure, unit-tested); agent-desk.tsx only
// reads the resulting numbers/booleans off AgentDeskState and renders Html overlays /
// one static translucent mesh. `concurrentSteps`/`deepTeamActive` come from the SAME
// office event stream deriveAgentDesks already walks (no second source of truth);
// `pendingCount` is computed by a SEPARATE pure function (derivePendingCounts) because
// its inputs (approvals + clarify questions) are REST-polled, not stream-derived — the
// office-unified screen calls both and threads the resulting Map<agentId, count> down
// as its own prop (desks stays the stream-derived map; pendingCounts is layered
// alongside it, not merged into it, so this module needs no knowledge of the REST types).
//
// Desks are keyed by `assigned_to`, NEVER by `author`: the ticker authors a step's `started`
// event as "coordinator" (it is the one dispatching, not the one doing the work) — the
// assignee identity rides in the body's `assigned_to` field instead (see
// `tick_actions.reserve_and_spawn` / `team_step_runner._append_step_event`). Keying by author
// would create a phantom "coordinator" desk that never leaves "working" and would leave real
// agents' desks empty until their first `handoff`.
//
// Real backend status vocabulary (grep `tick_actions.py`/`team_step_runner.py`): a
// `step_status` event's `status` is only ever `started` (ticker, dispatch) or `failed` (worker,
// terminal); a completed step is signaled by the `handoff` KIND, not a `step_status` status
// value — there is no `completed`/`done`/`in_progress` status string in production.
import type { OfficeMessage } from '../../../types'

export type AgentState = 'idle' | 'assigned' | 'working' | 'done' | 'error'

// Review verdict enum mirrors the server's closed set (`_REVIEW_VERDICTS` in
// office_event_projection.py) — anything else was already dropped to "" server-side.
export interface DeskVerdict {
  verdict: 'passed' | 'needs_rework'
  failureCount: number
  criteriaTotal: number
  criteriaPassed: number
  // Event timestamp (OfficeMessage.ts) — the RENDER layer uses it to fade the flash by
  // age, so a reconnect-replay of old events never re-flashes (reducer stays pure).
  ts: string
}

/**
 * What a working desk is doing RIGHT NOW, from `step_activity` (v80 P4).
 *
 * Telemetry, not state: it never moves the state machine, and it is cleared by the same
 * terminal events that end the step. `tool` is a registered tool NAME and `count` an int
 * — the projection guarantees no args or results ever reach this event
 * (office_event_projection.py, `step_recorder.ACTIVITY_FIELDS`). `phase` is the closed
 * pair 'calling-tool' | 'writing' (dropped to '' server-side if unrecognized), so the
 * render layer can distinguish "on the phone" from "at the keyboard" without parsing.
 */
export interface DeskActivity {
  tool: string
  count: number
  phase: string
}

export interface AgentDeskState {
  id: string
  state: AgentState
  taskTitle: string | null
  stepTitle: string | null
  // M31 self-check/rework graph: the step's mid-run phase tag ('dang-lam' | 'tu-soat' |
  // 'dang-sua'), null once no `step_status` event has carried one yet (e.g. before this
  // FE change ships, or the `handoff`/`assignment` paths that don't set it).
  phase: string | null
  // The `attempt_id` the CURRENT phase/state came from — used to drop a stale/zombie
  // attempt's out-of-order event (a retried step mints a fresh attempt_id; an
  // in-flight event from a superseded attempt must not overwrite the live one). Null
  // until the first `step_status` event with an attempt_id arrives for this desk.
  attemptId: string | null
  // M33: the colleague id THIS desk is currently consulting/being consulted by, null
  // when no consult bubble should show. Event-driven only (no timer): a `consult`
  // event SETS this on both the `from` and `to` desks; EITHER desk's own next event
  // of ANY other kind CLEARS it on BOTH (v14 — the consulted colleague may be idle
  // and never emit its own event, see `endConsult` below) — see the `consult` case
  // below + the endConsult call at the top of every other case.
  consultWith: string | null
  // Last review verdict THIS desk produced (it is the reviewer's desk, same keying as
  // the `review` case below). Advisory render layer only — never gates state.
  lastVerdict: DeskVerdict | null
  // v15 PIC: the task_ids this desk is currently PIC (chịu trách nhiệm chính) of.
  // Set by an `assignment` event's `pic`+`task_id`; a task_id is REMOVED by that
  // task's `milestone` event with the HARD field value `milestone === 'done'`
  // (team_tick_collaborators posts it at completion) — never by matching Vietnamese
  // message text. Badge shows while the set is non-empty. Multiple concurrent tasks
  // ⇒ multiple desks legitimately badged at once.
  picTasks: Set<string>
  // v54 P4: count of this desk's step_status dispatches (`started`, no attempt_id yet —
  // the ticker's own dispatch event, see tick_actions.reserve_and_spawn) that have not
  // been matched by a later terminal event (`failed`, `handoff`, or a `review` "done").
  // The dispatch/terminal events in this data model carry no per-step correlation id
  // (attempt_id only appears on the phase events AFTER dispatch — see the zombie-attempt
  // guard above), so this is a running counter, not an id-keyed set: it floors at 0
  // (a terminal event with nothing outstanding is a no-op, never negative). ×N fan-out
  // badge (agent-desk.tsx) shows while this is >= 2 — the agent has more than one step
  // dispatched to it at once (parallel fan-out).
  concurrentSteps: number
  // v54 P4: true while the desk's CURRENT attempt (per `attemptId` above) was dispatched
  // with `deep_team: true` on its phase event (P1's in-sandbox subagent-delegation
  // opt-in). Cleared whenever a fresh dispatch resets `attemptId`/`phase` (same moment
  // the zombie-attempt guard above clears the stale phase) or a terminal event resolves
  // this desk's work.
  deepTeamActive: boolean
  // Live in-step activity, or null when the desk is not mid-tool-call. Replaced (never
  // accumulated) by each new `step_activity`, and cleared by any terminal event.
  activity: DeskActivity | null
}

function nextState(prev: AgentState, status: string | undefined): AgentState {
  switch (status) {
    case 'started':
      return 'working'
    case 'failed':
      // Dual-lens P1: a failed step shows a real error visual (red desk + ⚠ bubble)
      // instead of silently freeing the desk to idle — the CEO must see breakage from
      // the office itself. The desk leaves 'error' on its own next dispatch/clarify
      // event (the cases above), exactly like every other transition.
      return 'error'
    case 'waiting_clarify':
      // v34 P2: paused mid-step on a CEO question — show the "has a task, not
      // actively working" visual (existing state, no new enum) until resume.
      return 'assigned'
    case 'needs_decision':
      // The step produced something, but it did not meet its acceptance criteria and
      // the coordinator has to decide what happens next. Shown with the same error
      // visual as a failed step: from the office floor both mean "this did not land",
      // and hiding it would be exactly the silence this status exists to break.
      return 'error'
    default:
      return prev
  }
}

// Reduces the full ordered event list into a per-agent desk-state map. Pure function — no
// A desk that has emitted nothing yet. Exported so the office screen can seed a desk
// for every CURRENT roster member even when the (tail-limited) stream carries no event
// of theirs — without this, an agent idle for longer than the tail window would have
// no desk at all (office-canvas renders nothing for a missing map entry).
export function idleDeskState(id: string): AgentDeskState {
  return {
    id, state: 'idle', taskTitle: null, stepTitle: null, phase: null, attemptId: null,
    consultWith: null, lastVerdict: null, picTasks: new Set<string>(),
    concurrentSteps: 0, deepTeamActive: false, activity: null,
  }
}

// Roster-complete desk list: event-derived ids keep their first-seen order (stable desk
// positions), roster members the stream hasn't mentioned append after in roster order.
export function withRosterIds(eventIds: string[], rosterIds: string[] | null): string[] {
  if (!rosterIds) return eventIds
  const seen = new Set(eventIds)
  return [...eventIds, ...rosterIds.filter((id) => !seen.has(id))]
}

// timers, no randomness — so the same event list always yields the same map (a re-render or a
// reconnect-replay is idempotent).
export function deriveAgentDesks(messages: OfficeMessage[]): Map<string, AgentDeskState> {
  const desks = new Map<string, AgentDeskState>()

  const ensure = (id: string): AgentDeskState => {
    let d = desks.get(id)
    if (!d) {
      d = idleDeskState(id)
      desks.set(id, d)
    }
    return d
  }

  // A consult ends for BOTH parties when EITHER desk gets its own next event (v14):
  // the asker moves on the moment its step emits anything, but the CONSULTED colleague
  // may be idle with no event of its own for hours — without the symmetric clear, its
  // avatar would stand at the meeting point indefinitely (review finding m3; pre-v14
  // this was just a lingering bubble, with walk-to-consult it is a stuck body).
  const endConsult = (d: AgentDeskState) => {
    if (d.consultWith) {
      const partner = desks.get(d.consultWith)
      if (partner && partner.consultWith === d.id) partner.consultWith = null
    }
    d.consultWith = null
  }

  for (const m of messages) {
    switch (m.kind) {
      case 'assignment': {
        // Task-level (coordinator-authored, no single assignee) — no state-machine
        // update. v15: a `pic`+`task_id` pair badges the PIC's desk (advisory layer,
        // like consultWith — never touches state/attempt/zombie logic).
        if (m.body.pic && m.body.task_id) ensure(m.body.pic).picTasks.add(m.body.task_id)
        break
      }
      case 'step_status': {
        const assignedTo = m.body.assigned_to
        if (!assignedTo) break // defensive: an event missing the field updates no desk
        const d = ensure(assignedTo)
        endConsult(d) // this desk moved on — the consult is over for BOTH parties
        const incomingAttempt = m.body.attempt_id ?? null
        // Zombie-attempt guard: the step graph's phase events (work/self_check/rework,
        // this phase's addition) carry the reserving `attempt_id`; the ticker's OWN
        // dispatch event (`tick_actions.py`, outside this phase's file ownership)
        // carries none. Treat a dispatch event (no attempt_id, status="started") as the
        // start of a NEW attempt and clear the desk's tracked attempt_id first — this is
        // what lets the attempt AFTER it freely adopt its own id below, and is what makes
        // a stale attempt's late-arriving phase event (from BEFORE that dispatch reset
        // things, delivered late by SSE reconnect-replay) get dropped instead of
        // silently overwriting the new attempt's live phase.
        if (!incomingAttempt && m.body.status === 'started') {
          // v54 P4: this IS the ticker's dispatch event (tick_actions.reserve_and_spawn)
          // — one more step is now live on this desk. Counted here (not on the phase
          // event) because the dispatch is the only event guaranteed to fire exactly
          // once per step, whereas phase events repeat mid-run.
          d.concurrentSteps += 1
          d.attemptId = null
          d.phase = null // a fresh dispatch invalidates the previous attempt's phase text
          d.deepTeamActive = false // the new attempt's own phase event will re-set this
          d.activity = null // a fresh dispatch invalidates the old attempt's telemetry
        } else if (incomingAttempt && d.attemptId && incomingAttempt !== d.attemptId) {
          break // stale attempt's phase event — drop
        } else if (incomingAttempt) {
          d.attemptId = incomingAttempt
        }
        if (m.body.status === 'failed' || m.body.status === 'needs_decision') {
          // Terminal for one dispatched step — floor at 0 so an out-of-order/replayed
          // failed (no matching outstanding dispatch counted, e.g. mid-stream join)
          // never goes negative. `needs_decision` is equally terminal for the DESK (the
          // agent is done working; the coordinator now decides what happens next), so it
          // must release the step here or the desk would show as working forever.
          d.concurrentSteps = Math.max(0, d.concurrentSteps - 1)
          d.deepTeamActive = false
          d.activity = null // the step is over — nothing is being called or written
        }
        // v54 P1/P4: deep_team rides the PHASE event (carries attempt_id), never the
        // bare dispatch — only set it while it belongs to the desk's CURRENT attempt.
        if (m.body.deep_team && incomingAttempt && incomingAttempt === d.attemptId) {
          d.deepTeamActive = true
        }
        d.taskTitle = m.body.task_title ?? d.taskTitle
        d.stepTitle = m.body.step_title ?? d.stepTitle
        d.phase = m.body.phase ?? d.phase
        d.state = nextState(d.state === 'idle' ? 'assigned' : d.state, m.body.status)
        break
      }
      case 'step_activity': {
        // Telemetry from the WORKER itself, so the agent is in `body.agent` — every other
        // kind here is ticker-authored and keys off `assigned_to`. Deliberately does NOT
        // call ensure(): desks exist because work was dispatched to them, and a stray or
        // replayed activity event must not conjure one. Touches nothing but `activity` —
        // no state, no attemptId, no consult — so late-arriving telemetry can never move
        // the state machine backwards.
        const agentId = m.body.agent
        if (!agentId) break
        const d = desks.get(agentId)
        if (!d) break
        d.activity = {
          tool: m.body.tool ?? '',
          count: m.body.count ?? 0,
          phase: m.body.phase ?? '',
        }
        break
      }
      case 'handoff': {
        const assignedTo = m.body.assigned_to ?? m.author
        const d = ensure(assignedTo)
        endConsult(d) // this desk moved on — the consult is over for BOTH parties
        // v54 P4: a handoff resolves one dispatched step (the "done" terminal for
        // step_status's "started"/"failed" pair) — same floor-at-0 posture as failed.
        d.concurrentSteps = Math.max(0, d.concurrentSteps - 1)
        d.deepTeamActive = false
        d.activity = null
        d.taskTitle = m.body.task_title ?? d.taskTitle
        d.stepTitle = m.body.step_title ?? d.stepTitle
        // A handoff marks the step as delivered to the next person — the desk shows "done"
        // until the SAME agent's next step_status/started moves it back to working.
        d.state = 'done'
        break
      }
      case 'milestone': {
        // Milestones are task-level (coordinator-authored), not desk state. v15: the
        // HARD `milestone === 'done'` value (posted by team_tick_collaborators at task
        // completion) releases every PIC badge keyed to that task_id.
        if (m.body.milestone === 'done' && m.body.task_id) {
          for (const d of desks.values()) d.picTasks.delete(m.body.task_id)
        }
        break
      }
      case 'review': {
        // M32: a review-step's own verdict — `assigned_to` here is the REVIEWER (the one
        // who ran the review-step), same desk-keying convention as `handoff`. Marks that
        // desk "done" like a handoff; the verdict/failure detail lives in the office room
        // timeline text (OfficeRoom.tsx), not the 3D desk state.
        const assignedTo = m.body.assigned_to ?? m.author
        const d = ensure(assignedTo)
        endConsult(d) // this desk moved on — the consult is over for BOTH parties
        // v54 P4: a review-step's verdict is its own terminal, same accounting as handoff.
        d.concurrentSteps = Math.max(0, d.concurrentSteps - 1)
        d.deepTeamActive = false
        d.activity = null
        d.taskTitle = m.body.task_title ?? d.taskTitle
        d.stepTitle = m.body.step_title ?? d.stepTitle
        d.state = 'done'
        // Dual-lens P1: keep the verdict for the render layer's pass/fail flash. The
        // server only lets the closed enum through; "" (unknown) sets nothing.
        if (m.body.verdict === 'passed' || m.body.verdict === 'needs_rework') {
          d.lastVerdict = {
            verdict: m.body.verdict,
            failureCount: m.body.failure_count ?? 0,
            criteriaTotal: m.body.criteria_total ?? 0,
            criteriaPassed: m.body.criteria_passed ?? 0,
            ts: m.ts,
          }
        }
        break
      }
      case 'consult': {
        // M33: a role-play consultation between two desks — set the bubble field on
        // BOTH ends (the asker and the colleague), event-driven only (see the field's
        // doc comment: cleared by either desk's own NEXT event, not a timer). A
        // consult never changes `state`/`taskTitle`/etc — it is advisory context
        // layered on top of whatever the desk is already doing.
        const from = m.body.from
        const to = m.body.to
        if (from) ensure(from).consultWith = to ?? null
        if (to) ensure(to).consultWith = from ?? null
        break
      }
      case 'ceo':
        break
      default:
        break
    }
  }

  return desks
}

// v17 Q4 (CEO decision): a desk speaks ONLY while actually working — a done/idle desk
// keeps its label/⭐ but shows no bubble (stale task titles no longer linger after a
// new task starts elsewhere). Consult is "happening now" and keeps the bubble alive.
// Dual-lens P1: an error is also "happening now" — the ⚠ bubble must not be silent.
export function shouldShowBubble(desk: AgentDeskState): boolean {
  return (
    desk.state === 'assigned' ||
    desk.state === 'working' ||
    desk.state === 'error' ||
    desk.consultWith !== null
  )
}

// Distinct agent ids seen in the stream, in first-seen order — drives desk layout (grid
// position assignment happens in office-canvas.tsx, not here). Uses the SAME `assigned_to`
// keying as deriveAgentDesks (never `author`) so the id list and the desk map always agree.
export function agentIdsInOrder(messages: OfficeMessage[]): string[] {
  const seen: string[] = []
  const set = new Set<string>()
  const add = (id: string | undefined) => {
    if (!id || set.has(id)) return
    set.add(id)
    seen.push(id)
  }
  for (const m of messages) {
    if (m.kind === 'step_status') add(m.body.assigned_to)
    if (m.kind === 'handoff') add(m.body.assigned_to ?? m.author)
    if (m.kind === 'review') add(m.body.assigned_to ?? m.author)
    if (m.kind === 'consult') {
      add(m.body.from)
      add(m.body.to)
    }
    // v15 (F8): the PIC's desk exists the moment the assignment lands — before any
    // step event names them — so the ⭐ badge is never invisible for lack of a desk.
    if (m.kind === 'assignment') add(m.body.pic)
  }
  return seen
}

// ✋ pending-count badge. Pure merge of the two lists that mean "someone is waiting on the
// CEO": the fleet-wide approvals index and the clarify questions. `use-office-orchestration`
// reads both once and passes the resulting map into the canvas, so the desk badge cannot
// disagree with whatever else renders the same queue.
//
// `agentId`/`agent_id` are the two lists' own field names (the approvals index is a server
// payload using snake_case; the caller maps it before handing it over) — kept as loose shape
// params here, not the full imported types, so this module stays a leaf with no dependency
// on the hooks/api layer.
export function derivePendingCounts(
  approvalItems: { agentId: string }[],
  clarifyItems: { agent_id: string }[],
): Map<string, number> {
  const counts = new Map<string, number>()
  const bump = (id: string) => counts.set(id, (counts.get(id) ?? 0) + 1)
  for (const a of approvalItems) bump(a.agentId)
  for (const c of clarifyItems) bump(c.agent_id)
  return counts
}
