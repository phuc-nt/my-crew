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

// --- ops payloads (S4) ---

export interface PendingAction {
  type?: string
  server?: string
  tool?: string
  args?: Record<string, unknown>
}

export interface ApprovalItem {
  id: number
  reason: string
  status: string
  created_at: string
  action: PendingAction
}

export interface ApprovalsPayload {
  agent_id: string
  pending: ApprovalItem[]
  approved?: number
  rejected?: number
}

export interface ConfigPayload {
  agent_id: string
  files: Record<string, string> // { profile, soul, project, memory }
}

export interface TriggerResult {
  run_id: string
  thread_id: string
}

// --- admin payloads (v3 M7: create wizard, team lifecycle, integration health) ---

export interface Pack {
  id: string
  name: string
  report_kinds: string[]
  servers: string[]
}

export interface PacksPayload {
  packs: Pack[]
}

export interface SlackBinding {
  report_channel?: string
  stakeholder_channel?: string
  external_channels?: string[]
}

export interface CreateAgentBindings {
  jira?: { project_key?: string }
  confluence?: { space_key?: string; space_id?: string; okr_page_id?: string }
  github?: { repo?: string }
  slack?: SlackBinding
}

export interface CreateAgentSpec {
  id: string
  name: string
  domain: string
  reports: string[]
  schedule: Record<string, string>
  bindings: CreateAgentBindings
  persona?: string
}

export interface CreateAgentResult {
  created: {
    id: string
    domain: string
    reports: string[]
  }
}

export interface EnabledResult {
  agent_id: string
  enabled: boolean
  // registry AND profile.yaml `enabled` — the value the service gate actually uses. A
  // resume can report enabled=true (registry flipped) while this stays false (profile
  // still vetoes it), so the UI must not treat `enabled: true` alone as "running".
  effective_enabled: boolean
}

export interface DeleteAgentResult {
  agent_id: string
  deleted: true
  profile_dir_kept: true
}

export interface IntegrationCheck {
  id: string
  label: string
  ok: boolean
  detail: string
  hint: string
}

export interface IntegrationHealthPayload {
  checks: IntegrationCheck[]
  checked_at: number
}
