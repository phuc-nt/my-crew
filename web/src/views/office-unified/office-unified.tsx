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
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api } from '../../api/client'
import { useLanguage } from '../../i18n/language-context'
import { useUiMode } from '../../ui-mode-context'
import { useOfficeStream } from '../../hooks/use-office-stream'
import { useSharedPendingApprovals } from '../../pending-approvals-context'
import {
  agentIdsInOrder, deriveAgentDesks, derivePendingCounts, idleDeskState, withRosterIds,
} from '../../features/office/office-3d/agent-office-state'
import { AgentStatusTable } from '../../components/agent-status-table'
import { use3dFallback } from '../../features/office/office-3d/use-3d-fallback'
import { Button } from '../../components/ui/button'
import { PageHeader } from '../../components/ui/page-header'
import type { ClarifyQuestion, OfficeMessage, TeamBoardLane, Workroom } from '../../types'
import { ActionRail } from './action-rail'
import { ActivityFeed } from '../../features/office/activity-feed'
import { ArtifactPanel } from './artifact-panel'
import { AssignComposer } from './assign-composer'
import { CoordinatorHealthBanner } from './coordinator-health-banner'
import { DeskInspector } from '../../features/office/desk-inspector'
import { OfficeHealthStrip } from './office-health-strip'
import { ReviewDetailTray } from './review-detail-tray'
import { WorkroomList } from './workroom-list'

// v82 perf: three/@react-three used to load INSIDE this chunk, so the whole office
// shell (composer, feed, rooms) waited on the 3D bundle before first paint. The canvas
// is now its own chunk; while it streams in, the lightweight status table stands in —
// same data, same desk clicks — so the screen is usable immediately.
const OfficeCanvas = lazy(() => import('../../features/office/office-3d/office-canvas'))

const OFFICE_ROOM_ID = 'office'
// Cold-connect tail for the aggregated `office` room: it mirrors EVERY event forever,
// so a full replay on first open grows without bound (real deployments hit thousands
// of rows — the CEO watched the feed chew through months of `skipped` noise before
// showing anything current). 300 comfortably covers the feed tail (40) and gives desk
// derivation enough recent context; roster seeding below covers agents idle for longer.
const OFFICE_COLD_TAIL = 300
const PANEL_COLLAPSE_KEY = 'office3dCollapsed'
// v54 P4: same cadence action-rail.tsx used for its own (now-removed) self-fetch.
const CLARIFY_POLL_MS = 30_000

export function OfficeUnified() {
  const { t } = useLanguage()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeRoom = searchParams.get('room') // null = toàn cảnh
  const [rooms, setRooms] = useState<Workroom[]>([])
  // localStorage is absent in some embedded/jsdom environments — collapse memory is a
  // nicety, never a requirement.
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(PANEL_COLLAPSE_KEY) === '1' } catch { return false }
  })
  const useFallback = use3dFallback()

  // Company identity — the office screen must say WHOSE office this is. Name comes
  // from company.yaml via /api/company; empty name renders a set-it-up hint instead.
  const [companyName, setCompanyName] = useState<string | null>(null)
  useEffect(() => {
    api.getCompany().then((c) => setCompanyName(c.name)).catch(() => setCompanyName(null))
  }, [])

  // Stream 1: the whole office — feeds the 3D panel (and the feed in toàn-cảnh mode).
  // Tail-limited: this room's history is unbounded (see OFFICE_COLD_TAIL).
  const office = useOfficeStream(OFFICE_ROOM_ID, OFFICE_COLD_TAIL)
  // Stream 2: the selected room — feeds the feed/composer context. Same id as stream 1
  // when no room is selected (see header note on the ≤2-connection budget); a per-task
  // workroom replays whole — its history IS the conversation.
  const room = useOfficeStream(activeRoom ?? OFFICE_ROOM_ID, activeRoom ? undefined : OFFICE_COLD_TAIL)

  // v54 P4: clarify fetch lifted here (was self-contained inside ActionRail) so the ✋
  // pending badge on the 3D desk reads the SAME poll the action rail displays — one
  // source of truth, no second EventSource/interval. Approvals already have a single
  // shared poll (usePendingApprovals via the context); this puts clarify on equal
  // footing before merging both into a per-agent count.
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([])
  const loadClarify = useCallback(() => {
    api.getClarifyPending().then((res) => setClarifyQuestions(res.questions)).catch(() => undefined)
  }, [])
  useEffect(() => {
    loadClarify()
    const timer = setInterval(loadClarify, CLARIFY_POLL_MS)
    return () => clearInterval(timer)
  }, [loadClarify])
  const { items: approvals } = useSharedPendingApprovals()
  const pendingCounts = useMemo(
    () => derivePendingCounts(approvals, clarifyQuestions),
    [approvals, clarifyQuestions],
  )

  // Registry roster — the ghost-desk filter. Coordinator is not assignable but owns the
  // center desk component, so only agent desks are filtered by this list.
  const [rosterIds, setRosterIds] = useState<string[] | null>(null)
  useEffect(() => {
    api.getAssignableStaff().then((p) => setRosterIds(p.staff.map((s) => s.id)))
      .catch(() => setRosterIds(null))
  }, [])

  // Desk inputs: events drive state, the roster completes coverage — with the stream
  // tail-limited, a long-idle agent may have no event in the window, but every CURRENT
  // staff member still deserves an (idle) desk in the office.
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
  // v54 P3: clicking a review feed line opens the per-criterion tray in the right
  // column — closes itself whenever the selected room changes so a stale review from a
  // different room's stream never lingers behind a new selection.
  const [reviewSelected, setReviewSelected] = useState<OfficeMessage | null>(null)
  useEffect(() => { setReviewSelected(null) }, [activeRoom])

  // v55: the right column is tabbed [Phòng việc | Kết quả] so results are one click away
  // instead of buried under the rooms list. A ● dot marks a handoff that landed LIVE while
  // the results tab wasn't open.
  //
  // v56 (4th attempt, caught by real-data UAT): "live" is decided by the EVENT'S OWN ts
  // versus when this room was opened — never by seq against a render-time baseline. The
  // SSE stream replays a room's history ASYNCHRONOUSLY after mount, so any baseline
  // captured during render is taken while messages are still empty, and the replay's old
  // handoffs out-seq it → dot from history (jsdom sets messages synchronously, which is
  // why the suite stayed green through all three earlier fixes). Same-machine clocks, so
  // event-ts vs Date.now() skew is negligible; an unparsable ts (NaN) counts as history.
  // Toàn-cảnh has no room (ArtifactPanel shows a pick-a-room hint) → dot suppressed —
  // the old {room: null} baseline sentinel collided with exactly that state and never
  // armed a baseline there at all.
  const [sideTab, setSideTab] = useState<'rooms' | 'results'>('rooms')
  const [resultsDot, setResultsDot] = useState(false)
  const openedAt = useRef<{ room: string | null | undefined; at: number }>({ room: undefined, at: 0 })
  if (openedAt.current.room !== activeRoom) {
    openedAt.current = { room: activeRoom, at: Date.now() }
  }
  const liveHandoff = activeRoom !== null && room.messages.some(
    (m) => m.kind === 'handoff' && Date.parse(m.ts) > openedAt.current.at,
  )
  useEffect(() => {
    if (liveHandoff && sideTab !== 'results') setResultsDot(true)
  }, [liveHandoff, sideTab])
  useEffect(() => { setResultsDot(false) }, [activeRoom]) // new room = fresh dot state
  useEffect(() => { if (sideTab === 'results') setResultsDot(false) }, [sideTab])
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
          how-to text folds into <details> so the working area starts higher. This header
          and the composer below span the full width of the layout-A grid. */}
      <div className="office-unified-header">
        <PageHeader
          title={
            <>
              {t('office.title')}
              {companyName !== null && (
                companyName
                  ? <span className="office-company-name"> · {companyName}</span>
                  : (
                    <Link className="office-company-name office-company-unset" to="/settings">
                      {t('office.companyUnset')}
                    </Link>
                  )
              )}
            </>
          }
          actions={
            <Button variant="chip" className="office-3d-toggle" onClick={toggleCollapsed}>
              {collapsed ? t('office.expand3d') : t('office.collapse3d')}
            </Button>
          }
        />
        <CoordinatorHealthBanner />
        {isHigh && <OfficeHealthStrip />}
        <details className="office-hint">
          <summary>{t('office.hintSummary')}</summary>
          <p className="ops-chat-hint">
            {t('office.hintBody')} <code>@tên-nhân-sự</code> {t('office.hintBodyMention')}{' '}
            <code>@all</code>
            {t('office.hintBodyAllPrefix')} {t('office.hintBodyAll')}
          </p>
        </details>
      </div>

      {/* v55 layout B: the composer sits directly under the header — giao việc is the
          first thing the CEO can do, on desktop AND in the mobile stack (DOM order). */}
      <AssignComposer activeRoom={activeRoom} onTaskCreated={(taskId) => selectRoom(taskId)} />

      {/* v54 layout A: rail trái (LÀM) — mobile DOM order puts this above the canvas/feed
          so blocking items stay first on narrow screens. */}
      <ActionRail clarifyQuestions={clarifyQuestions} onClarifyAnswered={loadClarify} />

      {/* center column (XEM): 3D canvas + live feed of the selected room. */}
      <div className="office-unified-center">
        {!collapsed && (
          <div className="office-unified-main">
            {useFallback ? (
              <AgentStatusTable
                agentIds={agentIds} desks={desks} onDeskSelect={openDesk}
                needsShellAgents={needsShellAgents}
              />
            ) : (
              <Suspense
                fallback={
                  <AgentStatusTable
                    agentIds={agentIds} desks={desks} onDeskSelect={openDesk}
                    needsShellAgents={needsShellAgents}
                  />
                }
              >
                <OfficeCanvas
                  agentIds={agentIds} desks={desks} rosterIds={rosterIds} dimmedIds={dimmedIds}
                  onDeskSelect={openDesk} needsShellAgents={needsShellAgents}
                  pendingCounts={pendingCounts}
                />
              </Suspense>
            )}
          </div>
        )}
        <ActivityFeed
          messages={room.messages} connected={room.connected} errored={room.errored}
          onReviewSelect={setReviewSelected}
        />
      </div>

      {/* right column (TRA), v55: tabbed [Phòng việc | Kết quả] — each tab gets the
          whole column height (cockpit shell scrolls .office-side-body internally). An
          open review tray takes over the column; closing it returns to the tabs. */}
      <div className="office-unified-side">
        {reviewSelected ? (
          <ReviewDetailTray message={reviewSelected} taskId={activeRoom} onClose={() => setReviewSelected(null)} />
        ) : (
          <>
            <div className="office-side-tabs" role="tablist">
              <Button
                variant="chip"
                className={sideTab === 'rooms' ? 'chip-active' : undefined}
                onClick={() => setSideTab('rooms')}
              >
                {t('officeSide.tabRooms')}
              </Button>
              <Button
                variant="chip"
                className={sideTab === 'results' ? 'chip-active' : undefined}
                onClick={() => setSideTab('results')}
              >
                {t('officeSide.tabResults')}
                {resultsDot ? <span className="office-side-badge">●</span> : null}
              </Button>
            </div>
            <div className="office-side-body">
              {sideTab === 'rooms' ? (
                <WorkroomList
                  rooms={rooms} activeRoom={activeRoom} onSelect={selectRoom}
                  needsShellRooms={needsShellRooms}
                />
              ) : (
                <ArtifactPanel activeRoom={activeRoom} roomMessages={room.messages} />
              )}
            </div>
          </>
        )}
      </div>

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
