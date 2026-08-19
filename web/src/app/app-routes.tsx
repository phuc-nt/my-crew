// Route table.
//
// Five hubs own every screen: /chat (home), /office, /work, /team, /system. Screens that
// used to be their own top-level route are now tabs inside a hub, and the pre-redesign
// URLs below survive as redirects so older links and bookmarks still land somewhere real.
import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router'
import { OfficePageLazy } from '../routes/office-page-lazy'
import { ChatPage } from '../features/chat/chat-page'
import { TeamPage } from '../features/team/team-page'
import { ASSISTANT_CONVERSATION_ID } from '../features/chat/conversation-list-state'
import { SystemPage } from '../features/system/system-page'
import { WorkPage } from '../features/work/work-page'
import { AppShell } from './app-shell'

// One agent's eight tabs pull in charts, config editors and the Telegram panel — a heavy
// tree that only matters once someone opens a specific agent, so it loads on demand.
const AgentDetailPage = lazy(() =>
  import('../features/team/agent-detail/agent-detail-page').then((m) => ({ default: m.AgentDetailPage })),
)

// One task's steps each carry an artifact + transcript renderer; that whole tree only
// matters once someone opens a specific task, so it loads on demand.
const TaskDetailPage = lazy(() =>
  import('../features/work/task-detail/task-detail-page').then((m) => ({
    default: m.TaskDetailPage,
  })),
)

/** `/agents/:id` carried the agent in the path; keep it rather than dropping to the roster. */
function AgentRedirect({ tab }: { tab: string }) {
  const { id } = useParams()
  if (!id) return <Navigate to="/team" replace />
  return <Navigate to={`/team/${encodeURIComponent(id)}?tab=${tab}`} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<AppShell />}>
        {/* Chat is the home screen of the new IA. */}
        <Route index element={<Navigate to="/chat" replace />} />

        {/* --- the 5 hubs --- */}
        {/* The chat hub owns an optional room segment: /chat is the overview thread. */}
        <Route path="chat" element={<ChatPage />} />
        <Route path="chat/:roomId" element={<ChatPage />} />
        <Route path="office" element={<OfficePageLazy />} />
        <Route path="work" element={<WorkPage />} />
        <Route
          path="work/task/:room"
          element={
            <Suspense fallback={null}>
              <TaskDetailPage />
            </Suspense>
          }
        />
        <Route path="team" element={<TeamPage />} />
        <Route
          path="team/:id"
          element={
            <Suspense fallback={null}>
              <AgentDetailPage />
            </Suspense>
          }
        />
        <Route path="system" element={<SystemPage />} />

        {/* --- legacy paths: every pre-redesign URL still resolves, now as a redirect ---
           Bookmarks and links printed in old reports must not 404. Each one lands on the
           hub tab that absorbed it, so the destination is the screen, not just the hub. */}
        {/* The chat hub owns the assistant conversation now. */}
        <Route
          path="assistant"
          element={<Navigate to={`/chat/${ASSISTANT_CONVERSATION_ID}`} replace />}
        />
        <Route path="settings" element={<Navigate to="/system?tab=settings" replace />} />
        <Route path="connections" element={<Navigate to="/system?tab=connections" replace />} />
        <Route path="company-docs" element={<Navigate to="/system?tab=company" replace />} />
        <Route path="captures" element={<Navigate to="/system?tab=audit" replace />} />
        <Route path="outputs" element={<Navigate to="/work?tab=outputs" replace />} />
        <Route path="company-activity" element={<Navigate to="/work?tab=activity" replace />} />
        <Route path="approvals" element={<Navigate to="/work" replace />} />
        <Route path="tasks" element={<Navigate to="/work" replace />} />
        <Route path="create" element={<Navigate to="/team" replace />} />
        {/* One agent's old routes: the id is in the path, so each keeps its agent. */}
        <Route path="agents/:id" element={<AgentRedirect tab="profile" />} />
        <Route path="overview" element={<Navigate to="/team" replace />} />
        <Route path="timeline" element={<Navigate to="/team" replace />} />
        <Route path="cost" element={<Navigate to="/team" replace />} />
        <Route path="memory" element={<Navigate to="/team" replace />} />
        <Route path="guardrail" element={<Navigate to="/team" replace />} />
        <Route path="config" element={<Navigate to="/team" replace />} />
        <Route path="trigger" element={<Navigate to="/team" replace />} />
        <Route path="office/timeline" element={<Navigate to="/office" replace />} />
        <Route path="office/3d" element={<Navigate to="/office" replace />} />

        {/* Any unknown path lands on the home hub rather than a blank screen. */}
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  )
}
