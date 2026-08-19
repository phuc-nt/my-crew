// Everything the office page knows, minus the layout.
//
// The old screen (views/office-unified/office-unified.tsx) held all of this inline —
// nine useState and ten useEffect wrapped around the JSX — so the data flow could only
// be read by reading the markup. It moves here unchanged in behavior: the same two
// EventSource budget, the same guarded refetch signals, the same resolve-time gates.
// The page below it becomes layout, and this becomes testable without a DOM.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { useUiMode } from '../../ui-mode-context'
import { useOfficeStream } from '../../hooks/use-office-stream'
import { usePendingApprovals } from '../../api/queries/use-approvals-queries'
import {
  agentIdsInOrder, deriveAgentDesks, derivePendingCounts, idleDeskState, withRosterIds,
} from './office-3d/agent-office-state'
import type { AgentDeskState } from './office-3d/agent-office-state'
import type { ClarifyQuestion, OfficeMessage, TeamBoardLane, Workroom } from '../../types'

export const OFFICE_ROOM_ID = 'office'
// Cold-connect tail for the aggregated `office` room: it mirrors EVERY event forever, so
// a full replay on first open grows without bound (real deployments hit thousands of rows
// — the CEO watched the feed chew through months of `skipped` noise before showing
// anything current). 300 comfortably covers the feed tail (40) and gives desk derivation
// enough recent context; roster seeding below covers agents idle for longer.
export const OFFICE_COLD_TAIL = 300
// Same cadence the action rail used for its own (since-removed) self-fetch.
const CLARIFY_POLL_MS = 30_000

export interface OfficeOrchestration {
  /** Desk floor. */
  agentIds: string[]
  desks: Map<string, AgentDeskState>
  rosterIds: string[] | null
  dimmedIds: Set<string>
  pendingCounts: Map<string, number>
  needsShellAgents: Set<string>
  needsShellRooms: Set<string>
  /** Streams. */
  officeMessages: OfficeMessage[]
  roomMessages: OfficeMessage[]
  connected: boolean
  errored: boolean
  /** Side data. */
  rooms: Workroom[]
  companyName: string | null
  clarifyQuestions: ClarifyQuestion[]
  reloadClarify: () => void
}

/**
 * @param activeRoom the selected workroom id, or null for toàn cảnh (whole office).
 */
export function useOfficeOrchestration(activeRoom: string | null): OfficeOrchestration {
  // Stream 1: the whole office — feeds the 3D floor (and the feed in toàn-cảnh mode).
  // Tail-limited: this room's history is unbounded (see OFFICE_COLD_TAIL).
  const office = useOfficeStream(OFFICE_ROOM_ID, OFFICE_COLD_TAIL)
  // Stream 2: the selected room. Same id as stream 1 when nothing is selected, which
  // holds the whole screen to AT MOST two EventSources; a per-task workroom replays
  // whole — its history IS the conversation.
  const room = useOfficeStream(
    activeRoom ?? OFFICE_ROOM_ID, activeRoom ? undefined : OFFICE_COLD_TAIL,
  )

  // Company identity — the office must say WHOSE office this is. An empty name is a
  // real answer (renders a set-it-up hint), so null means "not loaded / failed".
  const [companyName, setCompanyName] = useState<string | null>(null)
  useEffect(() => {
    api.getCompany().then((c) => setCompanyName(c.name)).catch(() => setCompanyName(null))
  }, [])

  // Clarify lives here, not inside the action rail, so the ✋ badge on a 3D desk and the
  // rail's own list read the SAME poll — one source of truth, no second interval.
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([])
  const reloadClarify = useCallback(() => {
    api.getClarifyPending().then((res) => setClarifyQuestions(res.questions)).catch(() => undefined)
  }, [])
  useEffect(() => {
    reloadClarify()
    const timer = setInterval(reloadClarify, CLARIFY_POLL_MS)
    return () => clearInterval(timer)
  }, [reloadClarify])
  // The fleet-wide index names the agent as `agent_id`; the desk badge counts per agent,
  // so map it into the shape the pure deriver expects rather than teaching it two spellings.
  const { data: approvals } = usePendingApprovals()
  const pendingCounts = useMemo(
    () => derivePendingCounts((approvals?.pending ?? []).map((a) => ({ agentId: a.agent_id })), clarifyQuestions),
    [approvals, clarifyQuestions],
  )

  // Registry roster — the ghost-desk filter. Desks render only for CURRENT staff, so a
  // departed agent's historical events cannot leave a desk on the floor.
  const [rosterIds, setRosterIds] = useState<string[] | null>(null)
  useEffect(() => {
    api.getAssignableStaff().then((p) => setRosterIds(p.staff.map((s) => s.id)))
      .catch(() => setRosterIds(null))
  }, [])

  // Desk inputs: events drive state, the roster completes coverage — with the stream
  // tail-limited a long-idle agent may have no event in the window, but every current
  // staff member still deserves an (idle) desk.
  const agentIds = useMemo(
    () => withRosterIds(agentIdsInOrder(office.messages), rosterIds),
    [office.messages, rosterIds],
  )
  const desks = useMemo(() => {
    const map = deriveAgentDesks(office.messages)
    for (const id of rosterIds ?? []) {
      if (!map.has(id)) map.set(id, idleDeskState(id))
    }
    return map
  }, [office.messages, rosterIds])

  // Sandbox-tier (needs_shell) badges come from the board API — the office stream's
  // allowlist does not carry tier data and stays untouched. `pic_id`/`room_id` are exact
  // joins, no title matching. Fetched only in high mode.
  const { isHigh } = useUiMode()
  const [boardLanes, setBoardLanes] = useState<TeamBoardLane[]>([])
  // Resolve-time gate: a board response landing AFTER the user toggled back to low mode
  // must not repopulate the lanes and leak 🔒 badges into a mode that never shows them.
  const isHighRef = useRef(isHigh)
  const loadBoard = useCallback(() => {
    api.getTeamTaskBoard()
      .then((p) => { if (isHighRef.current) setBoardLanes(p.lanes) })
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    isHighRef.current = isHigh
    if (isHigh) loadBoard()
    else setBoardLanes([])
  }, [isHigh, loadBoard])
  const { needsShellAgents, needsShellRooms } = useMemo(() => {
    const agents = new Set<string>()
    const roomsWithShell = new Set<string>()
    for (const lane of boardLanes) {
      if (lane.id === 'done' || lane.id === 'khac') continue // only live tasks badge
      for (const card of lane.cards) {
        if ((card.steps_needs_shell ?? 0) > 0) {
          if (card.pic_id) agents.add(card.pic_id)
          if (card.room_id) roomsWithShell.add(card.room_id)
        }
      }
    }
    return { needsShellAgents: agents, needsShellRooms: roomsWithShell }
  }, [boardLanes])

  // Rooms list — refetched only when a NEW assignment/milestone seq appears, so a busy
  // stream of step events does not hammer the endpoint.
  const [rooms, setRooms] = useState<Workroom[]>([])
  const lastRoomSignal = useRef(0)
  const loadRooms = useCallback(() => {
    api.getWorkrooms().then((p) => setRooms(p.rooms)).catch(() => undefined)
  }, [])
  useEffect(() => { loadRooms() }, [loadRooms])
  useEffect(() => {
    const signal = office.messages
      .filter((m) => m.kind === 'assignment' || m.kind === 'milestone')
      .reduce((mx, m) => Math.max(mx, m.seq), 0)
    if (signal > lastRoomSignal.current) {
      lastRoomSignal.current = signal
      loadRooms()
      if (isHigh) loadBoard() // same guarded signal — tier badges follow new tasks
    }
  }, [office.messages, loadRooms, isHigh, loadBoard])

  // Dim staff not involved in the selected room (derived from the ROOM stream).
  const dimmedIds = useMemo(() => {
    if (!activeRoom) return new Set<string>()
    const involved = new Set<string>()
    for (const m of room.messages) {
      if (m.body.assigned_to) involved.add(m.body.assigned_to)
      if (m.body.pic) involved.add(m.body.pic)
      if (m.body.from) involved.add(m.body.from)
      if (m.body.to) involved.add(m.body.to)
    }
    return new Set(agentIds.filter((id) => !involved.has(id)))
  }, [activeRoom, room.messages, agentIds])

  return {
    agentIds, desks, rosterIds, dimmedIds, pendingCounts, needsShellAgents, needsShellRooms,
    officeMessages: office.messages,
    roomMessages: room.messages,
    connected: room.connected,
    errored: room.errored,
    rooms, companyName, clarifyQuestions, reloadClarify,
  }
}
