// TypeScript types mirroring the backend JSON payloads (M2-P6 /api/agents + M4-S1 /api/*).
// Kept in sync by hand with src/server/agent_views.py + src/server/visualize_views.py.

export interface RunEvent {
  ts?: string
  kind?: string
  audience?: string
  status?: string
  cost_usd?: number | null
  delivered?: boolean
  auto_approved?: boolean // v8 M23: the trust ladder auto-delivered this scheduled report
}

export interface AgentSummary {
  id: string
  name: string
  enabled: boolean
  last_run: RunEvent | null
  // v10 M25: report kinds this agent's pack serves (drives the Trigger form). Optional so
  // older cached payloads / tests without it still typecheck.
  report_kinds?: string[]
  // v30: effective trust mode (server merges the yaml override over the env default).
  trust_mode?: 'autonomous' | 'guarded'
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
  trust_mode?: 'autonomous' | 'guarded'
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
  rationale?: string // v8 M23: carries the "auto_approve:*" marker for auto-approved actions
}

export interface AuditPayload {
  agent_id: string
  counts: Record<string, number>
  recent: AuditRow[]
}

// --- ops payloads (S4) ---

export interface PendingAction {
  // "mcp_tool" | "gh_cli" | "email_send" | "telegram_send"
  // | v31 native: "schedule_update" | "team_task_create" | "team_task_move" | "gws_write"
  type?: string
  server?: string
  tool?: string
  args?: Record<string, unknown> // mcp_tool: {projectKey, summary, channel, text, title, …}
  argv?: string[] // gh_cli / gws_write: ["pr", "merge", "45"] / ["sheets", "+append", …]
  to?: string | string[] // email_send: top-level (not in args); backend stores a recipient LIST
  subject?: string // email_send
  schedule?: Record<string, string> // schedule_update: {kind: cron}
  title?: string // team_task_create
  assignee?: string // team_task_create
  task_id?: string // team_task_move
  status?: string // team_task_move
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

// --- knowledge form + skills picker (v7 M18b) ---

// SOUL/PROJECT as a form: `fields` when the file is marker-parseable, else raw_mode=true
// and the UI falls back to the raw markdown editor (never overwrites hand-written prose).
export interface KnowledgePayload {
  doc: 'soul' | 'project'
  raw_mode: boolean
  fields: Record<string, string>
  raw: string
}

export interface SkillsPayload {
  skills: { name: string; description: string; selected: boolean }[]
}

// --- company docs library (v7 M19) ---

export interface CompanyDoc {
  slug: string
  title: string
  updated: string
  body: string
}

export interface AgentCompanyDocsPayload {
  docs: { slug: string; title: string; selected: boolean }[]
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
  web_search?: boolean
  // v30: omit ⇒ inherit the company-wide default (TRUST_MODE env).
  trust_mode?: 'autonomous' | 'guarded'
  // v20.5/v27: a bare kind string ('create_agent') OR, for deep_agent, a mapping carrying its
  // required sandbox block ('native' omitted = default). A bare 'deep_agent' string would be DOA
  // (missing sandbox), so the wizard emits the mapping form for it.
  agent_runtime?: string | { kind: string; sandbox: { provider: string } }
}

export interface CreateAgentResult {
  created: {
    id: string
    domain: string
    reports: string[]
  }
}

// --- company + staff templates ---

export interface CompanyPayload {
  name: string
  coordinator_id: string | null
  team_task_cap_usd: number
  // v15: present on reads; optional so older cached payload shapes still typecheck.
  team_task_concurrency?: number
  team_task_auto_confirm?: boolean
}

// v15 office composer (/api/office/assign/*)
export interface AssignStaffPayload {
  staff: { id: string; domain: string }[]
}

// v16 workrooms
export interface Workroom {
  room_id: string
  title: string
  task_count: number
  status: 'dang-chay' | 'ket' | 'xong'
  updated_at: string
}

export interface WorkroomsPayload {
  rooms: Workroom[]
}

export interface RoomChatPayload {
  intent: 'question' | 'adjust' | 'new_task'
  reply?: string
  preview_text?: string
  task_id?: string
  plan_hash?: string
  pic_id?: string
  amendment_id?: string
  auto_confirmed?: boolean
}

// v17 artifact viewer
export interface RoomArtifactStep {
  step_id: string
  title: string
  assigned_to: string
  status: string
  seq: number
  step_type: string
}

export interface RoomArtifactTask {
  task_id: string
  title: string
  pic_id: string
  status: string
  steps: RoomArtifactStep[]
}

export interface RoomArtifactsPayload {
  tasks: RoomArtifactTask[]
}

export interface StepArtifactPayload {
  task_id: string
  step_title: string
  result_text: string
  attempt: string
  self_check_failed: boolean
}

export interface CoordinatorHealthPayload {
  alive: boolean
  last_beat_ago_s: number | null
  reason: '' | 'no_coordinator' | 'no_heartbeat' | 'stale'
}

export interface AssignPreviewPayload {
  preview_text: string
  task_id: string
  plan_hash: string
  pic_id: string
  auto_confirmed: boolean
}

export interface StaffTemplate {
  role_id: string
  role: string
  domain: string
  reports: string[]
  bindings_hint: string[]
  persona: string
  web_search: boolean
  recommended_runtime: string // v20.5: 'native' | 'create_agent' | 'deep_agent'
}

export interface StaffTemplatesPayload {
  templates: StaffTemplate[]
}

// v18: profiles on disk missing from the registry (recovery listing)
export interface UnregisteredProfile {
  id: string
  name: string
  domain: string
  valid: boolean
  error?: string
}

export interface UnregisteredProfilesPayload {
  profiles: UnregisteredProfile[]
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

// v3 M8: deterministic fleet alerts (budget near cap, stuck approvals, deny spikes).
// v8 M21 adds the "agent chết ngầm" signals: missed_schedule + failing.
export interface TeamAlert {
  kind: 'budget' | 'approval_stuck' | 'deny_spike' | 'missed_schedule' | 'failing'
  agent_id: string
  message: string
  severity: 'warn' | 'high'
}

export interface TeamAlertsPayload {
  alerts: TeamAlert[]
}

// v6 M14b: CEO chat-ops web endpoint.
export interface OpsChatAvailable {
  available: boolean
  agent_id?: string
  reason?: string
}

export interface OpsChatReply {
  reply: string
  agent_id: string
}

// v6 M15b: assigned-tasks board.
export interface TaskHistoryEntry {
  ts: string
  summary: string
  cost_usd: number | null
}

export interface AssignedTask {
  id: number
  kind: 'watch' | 'report' | 'qa'
  params: Record<string, unknown>
  status: 'open' | 'running' | 'done' | 'cancelled' | 'stalled'
  created_at: string
  assigned_by: string
  history: TaskHistoryEntry[]
}

export interface AgentTasks {
  agent_id: string
  tasks: AssignedTask[]
}

export interface TasksPayload {
  agents: AgentTasks[]
}

// v12 M29: office group-chat room — SSE store-tail. `body` shape depends on `kind`
// (see src/server/office_event_projection.py's allowlist per kind).
// M33 adds 'consult': a role-play consultation over a colleague's public persona FILES
// (SOUL.md/PROJECT.md), NOT the sibling-memory system — see
// src/agent/team_task_consult.py's module docstring.
// M32 adds 'review': a peer-review verdict on a `work`/`rework` step — see
// src/agent/review_graph.py's module docstring.
export type OfficeEventKind =
  | 'ceo'
  | 'assignment'
  | 'step_status'
  | 'handoff'
  | 'milestone'
  | 'consult'
  | 'review'

export interface OfficeEventBody {
  text?: string
  task_title?: string
  step_title?: string
  step_count?: number
  summary?: string
  status?: string
  message?: string
  milestone?: string
  // `step_status`/`handoff` only: the agent id the desk-state reducer keys a desk by —
  // NEVER the event's `author` (a `step_status/started` event is authored by the
  // coordinator ticker, not the assignee doing the work).
  assigned_to?: string
  // `step_status` only (M31 self-check/rework graph): a closed-set phase tag the step
  // graph emits mid-run — 'dang-lam' | 'tu-soat' | 'dang-sua'. `attempt_id` rides
  // alongside it so the desk-state reducer can drop a stale/zombie attempt's phase
  // events (a retried step mints a fresh attempt_id; a superseded attempt's in-flight
  // phase event must not overwrite the current attempt's desk display).
  phase?: string
  attempt_id?: string
  // `consult` only (M33): `from`/`to` are agent ids; `question_summary`/`answer_summary`
  // are ~120-char TEMPLATE truncations (never raw file/answer content — see
  // office_event_projection.py's `consult` allowlist branch).
  from?: string
  to?: string
  question_summary?: string
  answer_summary?: string
  // `review` only (M32): `verdict` is a closed enum ('passed' | 'needs_rework'), never
  // free text; `failure_count` is a count only — the failure LIST never reaches the
  // room (see office_event_projection.py's `review` allowlist branch).
  verdict?: 'passed' | 'needs_rework'
  failure_count?: number
  // `assignment` only (v15 PIC): `pic` = agent id responsible for the whole task;
  // `task_id` (also on `milestone`) is the key the desk-state reducer uses to badge
  // the PIC's desk on assignment and clear it on that task's `milestone: done`.
  pic?: string
  task_id?: string
}

export interface OfficeMessage {
  seq: number
  ts: string
  author: string
  kind: OfficeEventKind
  body: OfficeEventBody
}

export interface OfficeRoomsPayload {
  rooms: string[]
}

// v31 P1: fleet-wide activity timeline ("Hoạt động công ty") — one merged, allowlisted
// item per audit decision / worker run / team-step attempt across every registry agent.
export interface CompanyActivityItem {
  ts: string | null
  agent_id: string
  source: 'audit' | 'run' | 'capture'
  // audit
  action_type?: string | null
  tool?: string | null
  verdict?: string | null
  reason?: string | null
  // run
  kind?: string | null
  audience?: string | null
  cost_usd?: number | null
  delivered?: boolean | null
  auto_approved?: boolean | null
  // capture (+ run shares `status`)
  status?: string | null
  task_id?: string | null
  step_id?: string | null
  engine?: string | null
  step_type?: string | null
}

export interface CompanyActivityPayload {
  items: CompanyActivityItem[]
  agents: string[]
  // agents whose data dir could not be read (degraded, not a 500)
  skipped: string[]
}
