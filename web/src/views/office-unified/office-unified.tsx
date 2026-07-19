// The workroom office screen (v16): rooms list (left) + live feed of the SELECTED room
// + chat-in-room composer, with the 3D panel always showing the WHOLE office.
//
// Stream budget (red-team C1): AT MOST 2 EventSources — the 3D panel always consumes
// room 'office' (every event mirrors there via also_office, so desks are complete
// regardless of selection); the feed consumes the selected room. In toàn-cảnh mode both
// ids are 'office', and the second hook simply duplicates the first's room id (two
// hooks, same room — an acceptable single extra connection ONLY while a room is open).
//
// Desk hygiene (v16): desks render only for CURRENT registry staff (rosterIds) — ghost
// desks from historical events are gone; selecting a room dims everyone not involved.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { api } from '../../api/client'
import { useUiMode } from '../../ui-mode-context'
import { useOfficeStream } from '../../hooks/use-office-stream'
import { agentIdsInOrder, deriveAgentDesks } from '../office-3d/agent-office-state'
import { AgentStatusTable } from '../office-3d/agent-status-table'
import { OfficeCanvas } from '../office-3d/office-canvas'
import { use3dFallback } from '../office-3d/use-3d-fallback'
import { Button } from '../../components/ui/button'
import type { TeamBoardLane, Workroom } from '../../types'
import { ActivityFeed } from './activity-feed'
import { ArtifactPanel } from './artifact-panel'
import { AssignComposer } from './assign-composer'
import { CoordinatorHealthBanner } from './coordinator-health-banner'
import { DeskInspector } from './desk-inspector'
import { OfficeHealthStrip } from './office-health-strip'
import { WorkroomList } from './workroom-list'

const OFFICE_ROOM_ID = 'office'
const PANEL_COLLAPSE_KEY = 'office3dCollapsed'

export function OfficeUnified() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeRoom = searchParams.get('room') // null = toàn cảnh
  const [rooms, setRooms] = useState<Workroom[]>([])
  // localStorage is absent in some embedded/jsdom environments — collapse memory is a
  // nicety, never a requirement.
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(PANEL_COLLAPSE_KEY) === '1' } catch { return false }
  })
  const useFallback = use3dFallback()

  // Stream 1: the whole office — feeds the 3D panel (and the feed in toàn-cảnh mode).
  const office = useOfficeStream(OFFICE_ROOM_ID)
  // Stream 2: the selected room — feeds the feed/composer context. Same id as stream 1
  // when no room is selected (see header note on the ≤2-connection budget).
  const room = useOfficeStream(activeRoom ?? OFFICE_ROOM_ID)

  const agentIds = useMemo(() => agentIdsInOrder(office.messages), [office.messages])
  const desks = useMemo(() => deriveAgentDesks(office.messages), [office.messages])

  // Registry roster — the ghost-desk filter. Coordinator is not assignable but owns the
  // center desk component, so only agent desks are filtered by this list.
  const [rosterIds, setRosterIds] = useState<string[] | null>(null)
  useEffect(() => {
    api.getAssignableStaff().then((p) => setRosterIds(p.staff.map((s) => s.id)))
      .catch(() => setRosterIds(null))
  }, [])

  // Dual-lens P1 (high-mode): sandbox-tier (needs_shell) badges come from the board
  // API — the office stream's allowlist does NOT carry tier data and stays untouched.
  // `pic_id`/`room_id` are exact joins; no title matching. Board is fetched only in
  // high mode and refetched on the same guarded signal as the rooms list.
  const { isHigh } = useUiMode()
  const [boardLanes, setBoardLanes] = useState<TeamBoardLane[]>([])
  // Resolve-time gate (review Low#1): a board response landing AFTER the user toggled
  // back to low mode must not repopulate the lanes and leak 🔒 badges into low mode.
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

  // Rooms list — refetch only when a NEW assignment/milestone seq shows up (guarded).
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

  // Dim staff not involved in the selected room (derived from the ROOM stream's events).
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

  const selectRoom = (roomId: string | null) => {
    setSearchParams(roomId ? { room: roomId } : {})
  }

  const navigate = useNavigate()
  // Dual-lens P2 (high mode): a desk click opens the Inspector drawer instead of
  // navigating — the maintainer inspects in place. Low mode keeps the v32 behavior.
  const [inspectorAgent, setInspectorAgent] = useState<string | null>(null)
  useEffect(() => {
    if (!isHigh) setInspectorAgent(null) // leaving high mode closes the drawer
  }, [isHigh])
  // v32 desk click: a PIC desk opens its task's workroom (room id = task id for a
  // standalone task; a child task's events mirror into its parent room via room_for_task
  // server-side, so the task id is still the room the FEED knows). A desk with no PIC
  // task opens the agent's own page — always a useful destination.
  const openDesk = useCallback(
    (agentId: string) => {
      if (isHigh) {
        setInspectorAgent(agentId)
        return
      }
      const desk = desks.get(agentId)
      const picTask = desk && desk.picTasks.size > 0 ? [...desk.picTasks][0] : null
      if (picTask && rooms.some((r) => r.room_id === picTask)) {
        selectRoom(picTask)
        return
      }
      navigate(`/agents/${agentId}`)
    },
    // selectRoom is a stable wrapper over setSearchParams; desks/rooms drive the mapping
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [desks, rooms, navigate, isHigh],
  )

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(PANEL_COLLAPSE_KEY, c ? '0' : '1') } catch { /* nicety only */ }
      return !c
    })
  }

  return (
    <section className="office-unified">
      {/* v33 P2: one compact header row — title left, panel toggle right; the long
          how-to text folds into <details> so the working area starts higher. */}
      <header className="office-header">
        <h2>Văn phòng</h2>
        <Button variant="chip" className="office-3d-toggle" onClick={toggleCollapsed}>
          {collapsed ? 'Hiện không gian 3D' : 'Thu gọn không gian 3D'}
        </Button>
      </header>
      <CoordinatorHealthBanner />
      {isHigh && <OfficeHealthStrip />}
      <details className="office-hint">
        <summary>Hướng dẫn nhanh</summary>
        <p className="ops-chat-hint">
          Bấm một bàn làm việc để mở việc của nhân sự đó; chọn phòng việc bên trái để xem
          hoạt động và chat; "Toàn cảnh" xem cả đội. Giao việc mới: gõ{' '}
          <code>@tên-nhân-sự</code> để chỉ định PIC, <code>@all</code>/bỏ trống để đội tự
          chọn.
        </p>
      </details>
      {!collapsed && (
        <div className="office-unified-main">
          {useFallback ? (
            <AgentStatusTable
              agentIds={agentIds} desks={desks} onDeskSelect={openDesk}
              needsShellAgents={needsShellAgents}
            />
          ) : (
            <OfficeCanvas
              agentIds={agentIds} desks={desks} rosterIds={rosterIds} dimmedIds={dimmedIds}
              onDeskSelect={openDesk} needsShellAgents={needsShellAgents}
            />
          )}
        </div>
      )}
      <div className="office-unified-layout office-columns">
        <WorkroomList
          rooms={rooms} activeRoom={activeRoom} onSelect={selectRoom}
          needsShellRooms={needsShellRooms}
        />
        <ActivityFeed
          messages={room.messages} connected={room.connected} errored={room.errored}
        />
        <ArtifactPanel activeRoom={activeRoom} roomMessages={room.messages} />
      </div>
      <AssignComposer activeRoom={activeRoom} onTaskCreated={(taskId) => selectRoom(taskId)} />
      {isHigh && inspectorAgent && (
        <DeskInspector
          agentId={inspectorAgent}
          desk={desks.get(inspectorAgent)}
          onClose={() => setInspectorAgent(null)}
        />
      )}
    </section>
  )
}

export default OfficeUnified
