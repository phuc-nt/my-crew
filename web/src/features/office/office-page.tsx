// The office hub: a viewing deck, not a workbench.
//
// `/office` answers one question — what is the whole company doing right now — with the
// 3D floor as the primary surface, a live feed beside it, and an inspector for one desk.
// Giao việc lives in the chat hub; the quick-assign modal here is a shortcut into that
// same composer, not a second implementation of it.
//
// All data flow lives in use-office-orchestration.ts; this file is layout. Stable
// `data-testid` hooks are deliberate — the e2e specs select on them, so restyling the
// office can never silently break the suite.
import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { Button } from '../../components/ui/button'
import { PageHeader } from '../../components/ui/page-header'
import { AgentStatusTable } from '../../components/agent-status-table'
import { useLanguage } from '../../i18n/language-context'
import { useUiMode } from '../../ui-mode-context'
import { ActivityFeed } from './activity-feed'
import { DeskInspector } from './desk-inspector'
import { QuickAssignModal } from './quick-assign-modal'
import { use3dFallback } from './office-3d/use-3d-fallback'
import { useOfficeOrchestration } from './use-office-orchestration'
import { CoordinatorHealthBanner } from '../../views/office-unified/coordinator-health-banner'
import { OfficeHealthStrip } from '../../views/office-unified/office-health-strip'
import { ReviewDetailTray } from '../../views/office-unified/review-detail-tray'
import { WorkroomList } from '../../views/office-unified/workroom-list'
import type { OfficeMessage } from '../../types'

// three/@react-three load in their own chunk so the office shell paints before the
// scene arrives; the lightweight status table stands in meanwhile — same data, same
// desk clicks — and IS the permanent surface when the fallback applies.
const OfficeCanvas = lazy(() => import('./office-3d/office-canvas'))

const PANEL_COLLAPSE_KEY = 'office3dCollapsed'

export function OfficePage() {
  const { t } = useLanguage()
  const { isHigh } = useUiMode()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeRoom = searchParams.get('room') // null = toàn cảnh
  const office = useOfficeOrchestration(activeRoom)
  const useFallback = use3dFallback()

  // localStorage is absent in some embedded/jsdom environments — collapse memory is a
  // nicety, never a requirement.
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(PANEL_COLLAPSE_KEY) === '1' } catch { return false }
  })
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(PANEL_COLLAPSE_KEY, c ? '0' : '1') } catch { /* nicety only */ }
      return !c
    })
  }

  const selectRoom = useCallback(
    (roomId: string | null) => setSearchParams(roomId ? { room: roomId } : {}),
    [setSearchParams],
  )

  // A desk click inspects in place — this is the observation deck, so the answer to
  // "what is this agent doing" belongs here rather than one navigation away. The
  // inspector's own links lead onward for anyone who wants the full page.
  const [inspectorAgent, setInspectorAgent] = useState<string | null>(null)
  const [quickAssign, setQuickAssign] = useState(false)
  const openDesk = useCallback((agentId: string) => setInspectorAgent(agentId), [])

  // A review line opens its per-criterion detail; a room change closes it so a stale
  // review from another room's stream never lingers behind a new selection.
  const [reviewSelected, setReviewSelected] = useState<OfficeMessage | null>(null)
  useEffect(() => { setReviewSelected(null) }, [activeRoom])

  const floor = (
    <AgentStatusTable
      agentIds={office.agentIds} desks={office.desks} onDeskSelect={openDesk}
      needsShellAgents={office.needsShellAgents}
    />
  )

  return (
    <section className="office-unified" data-testid="office-page">
      <div className="office-unified-header">
        <PageHeader
          title={
            <>
              {t('office.title')}
              {office.companyName !== null && (
                office.companyName
                  ? <span className="office-company-name"> · {office.companyName}</span>
                  : (
                    <Link className="office-company-name office-company-unset" to="/system?tab=company">
                      {t('office.companyUnset')}
                    </Link>
                  )
              )}
            </>
          }
          actions={
            <>
              <Button
                variant="chip" onClick={() => setQuickAssign(true)}
                data-testid="office-quick-assign"
              >
                {t('office.quickAssign')}
              </Button>
              <Button variant="chip" className="office-3d-toggle" onClick={toggleCollapsed}>
                {collapsed ? t('office.expand3d') : t('office.collapse3d')}
              </Button>
            </>
          }
        />
        <CoordinatorHealthBanner />
        {isHigh && <OfficeHealthStrip />}
      </div>

      <div className="office-unified-center">
        {!collapsed && (
          <div className="office-unified-main" data-testid="office-floor">
            {useFallback ? floor : (
              <Suspense fallback={floor}>
                <OfficeCanvas
                  agentIds={office.agentIds} desks={office.desks} rosterIds={office.rosterIds}
                  dimmedIds={office.dimmedIds} onDeskSelect={openDesk}
                  needsShellAgents={office.needsShellAgents} pendingCounts={office.pendingCounts}
                />
              </Suspense>
            )}
          </div>
        )}
        <ActivityFeed
          messages={office.roomMessages} connected={office.connected} errored={office.errored}
          onReviewSelect={setReviewSelected}
        />
      </div>

      {/* An open review takes over the column; closing it returns to the rooms list. */}
      <div className="office-unified-side" data-testid="office-rooms">
        {reviewSelected ? (
          <ReviewDetailTray
            message={reviewSelected} taskId={activeRoom}
            onClose={() => setReviewSelected(null)}
          />
        ) : (
          <WorkroomList
            rooms={office.rooms} activeRoom={activeRoom} onSelect={selectRoom}
            needsShellRooms={office.needsShellRooms}
          />
        )}
      </div>

      {inspectorAgent && (
        <DeskInspector
          agentId={inspectorAgent}
          desk={office.desks.get(inspectorAgent)}
          onClose={() => setInspectorAgent(null)}
        />
      )}
      {quickAssign && (
        <QuickAssignModal
          activeRoom={activeRoom}
          onClose={() => setQuickAssign(false)}
          onTaskCreated={(taskId) => { setQuickAssign(false); navigate(`/chat/${taskId}`) }}
        />
      )}
    </section>
  )
}

export default OfficePage
