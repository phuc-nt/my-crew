// Route table.
//
// Phase 1 stands the 5-hub shell up WITHOUT rebuilding any screen: each hub points at
// the closest existing view, and every legacy path still resolves at its old URL. That
// keeps bookmarks working and means this phase can be shipped on its own — later phases
// swap a hub's element and turn its legacy paths into redirects, one hub at a time.
import { Navigate, Route, Routes } from 'react-router'
import { AdvancedAgentView } from '../components/AdvancedAgentView'
import { OfficeUnifiedLazy } from '../routes/office-unified-lazy'
import { AgentPage } from '../views/AgentPage'
import { Captures } from '../views/Captures'
import { ChatPage } from '../features/chat/chat-page'
import { ASSISTANT_CONVERSATION_ID } from '../features/chat/conversation-list-state'
import { CompanyActivity } from '../views/CompanyActivity'
import { CompanyDocs } from '../views/CompanyDocs'
import { Config } from '../views/Config'
import { Connections } from '../views/Connections'
import { Cost } from '../views/Cost'
import { CreateAgent } from '../views/CreateAgent'
import { Guardrail } from '../views/Guardrail'
import { MemoryAutomation } from '../views/MemoryAuto'
import { OfficeRoom } from '../views/OfficeRoom'
import { Outputs } from '../views/Outputs'
import { Overview } from '../views/Overview'
import { Settings } from '../views/Settings'
import { Team } from '../views/Team'
import { Timeline } from '../views/Timeline'
import { Trigger } from '../views/Trigger'
import { Work } from '../views/Work'
import { AppShell } from './app-shell'

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
        <Route path="office" element={<OfficeUnifiedLazy />} />
        <Route path="work" element={<Work />} />
        <Route path="team" element={<Team />} />
        {/* No system hub yet (phase 6) — settings is its closest existing surface. */}
        <Route path="system" element={<Settings />} />

        {/* --- legacy paths, still live at their old URLs until their hub absorbs them --- */}
        {/* The chat hub owns the assistant conversation now; the old standalone path
           redirects so any bookmark still lands on it. */}
        <Route path="assistant" element={<Navigate to={`/chat/${ASSISTANT_CONVERSATION_ID}`} replace />} />
        <Route path="settings" element={<Settings />} />
        <Route path="connections" element={<Connections />} />
        <Route path="outputs" element={<Outputs />} />
        <Route path="agents/:id" element={<AgentPage />} />
        <Route path="create" element={<CreateAgent />} />
        <Route path="company-docs" element={<CompanyDocs />} />
        <Route path="company-activity" element={<CompanyActivity />} />
        <Route path="captures" element={<Captures />} />
        <Route path="office/timeline" element={<OfficeRoom />} />
        <Route path="office/3d" element={<Navigate to="/office" replace />} />
        <Route element={<AdvancedAgentView />}>
          <Route path="overview" element={<Overview />} />
          <Route path="timeline" element={<Timeline />} />
          <Route path="cost" element={<Cost />} />
          <Route path="memory" element={<MemoryAutomation />} />
          <Route path="guardrail" element={<Guardrail />} />
          <Route path="config" element={<Config />} />
          <Route path="trigger" element={<Trigger />} />
        </Route>
        <Route path="approvals" element={<Navigate to="/work" replace />} />
        <Route path="tasks" element={<Navigate to="/work" replace />} />

        {/* Any unknown path lands on the home hub rather than a blank screen. */}
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  )
}
