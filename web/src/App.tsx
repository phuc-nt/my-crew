// Router root. browser-router at `/` — the SPA is served at the root by FastAPI's
// StaticFiles(html=True) mount (S5); client routes deep-link via the index.html catch-all.
import { BrowserRouter, Route, Routes } from 'react-router'
import './App.css'
import { AgentProvider } from './agent-context'
import { Layout } from './components/Layout'
import { Approvals } from './views/Approvals'
import { Config } from './views/Config'
import { Cost } from './views/Cost'
import { Guardrail } from './views/Guardrail'
import { MemoryAutomation } from './views/MemoryAuto'
import { Overview } from './views/Overview'
import { Timeline } from './views/Timeline'
import { Trigger } from './views/Trigger'

function App() {
  return (
    <BrowserRouter>
      <AgentProvider>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="timeline" element={<Timeline />} />
            <Route path="cost" element={<Cost />} />
            <Route path="memory" element={<MemoryAutomation />} />
            <Route path="guardrail" element={<Guardrail />} />
            <Route path="approvals" element={<Approvals />} />
            <Route path="config" element={<Config />} />
            <Route path="trigger" element={<Trigger />} />
          </Route>
        </Routes>
      </AgentProvider>
    </BrowserRouter>
  )
}

export default App
