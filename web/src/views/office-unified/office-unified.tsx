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
import { useOfficeStream } from '../../hooks/use-office-stream'
import { agentIdsInOrder, deriveAgentDesks } from '../office-3d/agent-office-state'
import { AgentStatusTable } from '../office-3d/agent-status-table'
import { OfficeCanvas } from '../office-3d/office-canvas'
import { use3dFallback } from '../office-3d/use-3d-fallback'
import type { Workroom } from '../../types'
import { ActivityFeed } from './activity-feed'
import { ArtifactPanel } from './artifact-panel'
import { AssignComposer } from './assign-composer'
import { CoordinatorHealthBanner } from './coordinator-health-banner'
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
    }
  }, [office.messages, loadRooms])

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
  // v32 desk click: a PIC desk opens its task's workroom (room id = task id for a
  // standalone task; a child task's events mirror into its parent room via room_for_task
  // server-side, so the task id is still the room the FEED knows). A desk with no PIC
  // task opens the agent's own page — always a useful destination.
  const openDesk = useCallback(
    (agentId: string) => {
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
    [desks, rooms, navigate],
  )

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(PANEL_COLLAPSE_KEY, c ? '0' : '1') } catch { /* nicety only */ }
      return !c
    })
  }

  return (
    <section className="office-unified">
      <h2>Văn phòng</h2>
      <CoordinatorHealthBanner />
      <p className="ops-chat-hint">
        Bấm một bàn làm việc để mở việc của nhân sự đó; chọn phòng việc bên trái để xem hoạt động và chat; "Toàn cảnh" xem cả
        đội. Giao việc mới: gõ <code>@tên-nhân-sự</code> để chỉ định PIC, <code>@all</code>/bỏ
        trống để đội tự chọn.
      </p>
      <button type="button" className="chip office-3d-toggle" onClick={toggleCollapsed}>
        {collapsed ? 'Hiện không gian 3D' : 'Thu gọn không gian 3D'}
      </button>
      {!collapsed && (
        <div className="office-unified-main">
          {useFallback ? (
            <AgentStatusTable agentIds={agentIds} desks={desks} onDeskSelect={openDesk} />
          ) : (
            <OfficeCanvas
              agentIds={agentIds} desks={desks} rosterIds={rosterIds} dimmedIds={dimmedIds}
              onDeskSelect={openDesk}
            />
          )}
        </div>
      )}
      <div className="office-unified-layout office-columns">
        <WorkroomList rooms={rooms} activeRoom={activeRoom} onSelect={selectRoom} />
        <ActivityFeed
          messages={room.messages} connected={room.connected} errored={room.errored}
        />
        <ArtifactPanel activeRoom={activeRoom} roomMessages={room.messages} />
      </div>
      <AssignComposer activeRoom={activeRoom} onTaskCreated={(taskId) => selectRoom(taskId)} />
    </section>
  )
}

export default OfficeUnified
