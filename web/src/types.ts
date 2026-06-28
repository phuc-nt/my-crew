// TypeScript types mirroring the backend JSON payloads (M2-P6 /api/agents + M4-S1 /api/*).
// Kept in sync by hand with src/server/agent_views.py + src/server/visualize_views.py.

export interface RunEvent {
  ts?: string
  kind?: string
  audience?: string
  status?: string
  cost_usd?: number | null
  delivered?: boolean
}

export interface AgentSummary {
  id: string
  name: string
  enabled: boolean
  last_run: RunEvent | null
}

export interface Budget {
  spent: number
  cap: number
  ratio: number
}

export interface AgentStatus {
  id: string
  name: string
  enabled: boolean
  last_run: RunEvent | null
  budget: Budget
  pending_approvals: number
}

// --- M4-S1 visualization payloads ---

export interface RunsPayload {
  agent_id: string
  runs: RunEvent[]
}

export interface CostMonth {
  month: string
  total_usd: number
}

export interface CostPayload {
  agent_id: string
  series: CostMonth[]
  cap: number
  warn_ratio: number
  spent_this_month: number
}

export interface Fact {
  fact: string | null
  ts: string | null
  key: string | null
}

export interface MemoryPayload {
  agent_id: string
  facts: Fact[]
  internal_only: boolean
}

export interface Proposal {
  id: number
  reason: string
  status: string
  created_at: string
  action_summary: string
}

export interface AutomationPayload {
  agent_id: string
  pending: Proposal[]
}

export interface AuditRow {
  timestamp?: string
  action_type?: string
  tool?: string
  verdict?: string
  reason?: string
}

export interface AuditPayload {
  agent_id: string
  counts: Record<string, number>
  recent: AuditRow[]
}
