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
  actor?: string // v46: the agent (profile_id) that performed the action; "" for operator/CLI
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

/** One row of the fleet-wide pending index. `agent_id` is what makes the per-agent
 *  approve/reject URL buildable from a flat, cross-agent list. */
export interface FleetApprovalItem extends ApprovalItem {
  agent_id: string
}

export interface PendingApprovalsIndex {
  pending: FleetApprovalItem[]
  count: number
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
  deep_team?: boolean // v50 (v43): in-sandbox subagent coordination; only sent for deep_agent
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
  // v88 P5-D: present on reads; optional for the same cached-payload-shape reason.
  autopilot?: boolean
}

// v15 office composer (/api/office/assign/*)
export interface AssignStaffPayload {
  // v56: `web_search` = the agent's profile opt-in; `web_search_ready` = a search
  // provider key exists on the machine (presence-only, never a key name/value). Both
  // optional so older cached payloads still typecheck.
  staff: { id: string; domain: string; web_search?: boolean }[]
  web_search_ready?: boolean
}

// v16 workrooms
export interface Workroom {
  room_id: string
  title: string
  task_count: number
  status: 'dang-chay' | 'ket' | 'xong'
  updated_at: string
  /** Highest event seq in this room. The unread badge is this minus the last seq the
   *  reader saw. 0 for a room whose task exists but that has no events yet. */
  last_seq: number
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
  // v82: routing-funnel outcome ('sprint' | 'team') for the composer's mode badge.
  route_mode?: string
}

// Step types whose "done" carries a handoff artifact file — mirror of the server's
// routes_outputs._DELIVERED_TYPES. A type listed here but not there opens a viewer
// that 404s; one there but not here hides delivered work (sprint was invisible).
export const DELIVERED_STEP_TYPES: ReadonlySet<string> = new Set(['work', 'sprint', 'rework'])

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

// v82: one parsed transcript event (v80 recorder JSONL line) — `t` is the event kind
// (meta/tool_call/tool_result/prefetch/llm_request/llm_response/loop_input/outcome);
// the rest of the fields vary by kind, so they stay an open index.
export interface StepTranscriptEvent {
  t: string
  [key: string]: unknown
}

export interface StepTranscriptPayload {
  task_id: string
  step_id: string
  seq: number
  attempts: number
  events: StepTranscriptEvent[]
}

export interface CoordinatorHealthPayload {
  alive: boolean
  last_beat_ago_s: number | null
  reason: '' | 'no_coordinator' | 'no_heartbeat' | 'stale'
  hint: string
}

export interface AssignPreviewPayload {
  preview_text: string
  task_id: string
  plan_hash: string
  pic_id: string
  auto_confirmed: boolean
  // v82: routing-funnel outcome ('sprint' | 'team'). Optional — a pre-v82 server
  // omits it and the composer simply renders no mode badge.
  route_mode?: string
  // v87 P2: the previewed PIC's EFFECTIVE dry-run (profile override -> fleet env ->
  // default true) — the same resolution the worker runs with, so the composer can warn
  // BEFORE confirm instead of the CEO discovering "nothing was sent" after the fact.
  // Optional — a pre-v87 server omits it and the composer shows no dry-run badge.
  pic_dry_run?: boolean
}

// v87 P2: effective per-agent dry-run + toggle write result (GET/PATCH
// /api/agents/{id}/safety).
export interface AgentSafetyPayload {
  agent_id: string
  dry_run: boolean
  // GET only: whether `dry_run` comes from an explicit profile.yaml override or is
  // inherited from the fleet DRY_RUN env/default.
  dry_run_source?: 'profile' | 'fleet'
  // PATCH only: always false today (both dispatch paths re-read profile.yaml fresh
  // per run) — carried so the FE never has to assume and can render a restart hint if
  // a future backend ever needs one, same shape as ConnectionKeysResult.needs_restart.
  needs_restart?: boolean
}

// v88 P4: structured agent config form (GET/PATCH /api/agents/{id}/profile-settings).
// Values are the RAW ones written in profile.yaml — an absent `model`/empty
// `model_chain`/absent `budget_monthly_usd` means "follow the fleet default", not "0".
export interface AgentProfileSettingsPayload {
  agent_id: string
  name: string | null
  model: string | null
  model_chain: string[]
  budget_monthly_usd: number | null
  schedule: Record<string, string> // {kind: cron_expr} — same shape as create-time
}

// PATCH body: every field optional — only the keys present are patched.
export interface AgentProfileSettingsPatch {
  name?: string
  model?: string
  model_chain?: string[]
  budget_monthly_usd?: number
  schedule?: Record<string, string>
}

export interface AgentProfileSettingsPatchResult {
  agent_id: string
  needs_restart: boolean
}

// v88 P4: autonomy band — supervised (mọi bước soát chéo) | normal | trusted (bớt soát
// bước thường). NOT a profile.yaml key — a separate BandStore side-effect.
export type AgentBand = 'supervised' | 'normal' | 'trusted'

export interface AgentBandResult {
  agent_id: string
  band: AgentBand
}

// v88 P4: model dropdown suggestions read from config/model_prices.yaml — never
// hardcoded, never fetched from OpenRouter. Free-text is always allowed alongside it.
export interface ModelCatalogPayload {
  models: string[]
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
  // v32 one-click contract: pre-attached tools + default schedule + bundled skills
  academic_search: boolean
  schedule: Record<string, string>
  has_skills: boolean
}

// v32: one-click create + crew bootstrap payloads
export interface CreateFromTemplateResult {
  id: string
  domain: string
  reports: string[]
  name: string
  hint: string
}

export interface CrewMemberPreview {
  role_id: string
  role: string
  domain: string
  exists: boolean
}

export interface CrewPreview {
  crew_id: string
  crew: string
  members: CrewMemberPreview[]
  coordinator: string
  coordinator_already_set: boolean
  current_coordinator: string | null
}

export interface CrewCreateResult {
  crew_id: string
  crew: string
  created: string[]
  skipped: string[]
  failed: { role_id: string; error: string }[]
  coordinator_id: string | null
}

// v71: one entry per manifest in profiles/templates/crews/ — the 1-click crew choice.
export interface CrewOption {
  id: string
  name: string
  member_count: number
}

export interface CrewsPayload {
  crews: CrewOption[]
  default: string
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
// v32: discoverable ops-command listing for the Chat view
export interface OpsChatCommand {
  id: string
  description: string
  readonly: boolean
  // v88 P5-C: a runnable example the Chat box seeds into the composer on click — the
  // route falls back to the bare command id when a catalog entry defines none.
  example: string
}

export interface OpsChatAvailable {
  available: boolean
  agent_id?: string
  reason?: string
}

export interface OpsChatReply {
  reply: string
  agent_id: string
}

// v12 M29: office group-chat room — SSE store-tail. `body` shape depends on `kind`
// (see src/server/office_event_projection.py's allowlist per kind).
// M33 adds 'consult': a role-play consultation over a colleague's public persona FILES
// (SOUL.md/PROJECT.md), NOT the sibling-memory system — see
// src/agent/team_task_consult.py's module docstring.
// M32 adds 'review': a peer-review verdict on a `work`/`rework` step — see
// src/agent/review_graph.py's module docstring.
// v54 adds 'external_action': the Action Gateway outcome bridge — one event per
// gateway `_record` call (allow/deny/pending/dry_run/skipped/reject), no-content-echo
// (tool label + short target only — see office_event_projection.py's `external_action`
// allowlist branch).
export type OfficeEventKind =
  | 'ceo'
  | 'assignment'
  | 'step_status'
  | 'handoff'
  | 'milestone'
  | 'consult'
  | 'review'
  | 'external_action'
  // v80 P4: live in-step activity — one event per tool call / LLM request while a step
  // runs ("content-01 đang gọi web_search (3)"). Ids + tool NAME + counter only; the
  // tool's args/results never reach the room (office_event_projection.py `step_activity`).
  | 'step_activity'
  // Advisor ride-along: a second model reads a running step's transcript delta and
  // leaves a short note. `severity` is a closed enum ("nit" | "concern"); `message` is
  // the note itself, capped server-side to the consult tier
  // (office_event_projection.py `advisor`).
  | 'advisor'

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
  // v34 P5: per-criterion COUNTS (same count-only posture as failure_count).
  criteria_total?: number
  criteria_passed?: number
  // `assignment` only (v15 PIC): `pic` = agent id responsible for the whole task;
  // `task_id` (also on `milestone`) is the key the desk-state reducer uses to badge
  // the PIC's desk on assignment and clear it on that task's `milestone: done`.
  pic?: string
  task_id?: string
  // `step_status` only (v54): present (always `true`) only when the runtime dispatched
  // this step with the agent's `deep_team` (in-sandbox subagent delegation) opt-in on —
  // omitted entirely otherwise, keeping every pre-v54 event byte-identical.
  deep_team?: true
  // `external_action` only (v54): the Action Gateway outcome bridge. `outcome` mirrors
  // `GatewayResult.status`'s underlying verdict ("allow" | "deny" | "pending" | "dry_run"
  // | "skipped" | "reject"); `detail` is a short non-content target (channel/issue-key/
  // recipient id), never a message body.
  actor?: string
  tool?: string
  action_type?: string
  outcome?: string
  detail?: string
  // `step_activity` only (v80 P4): `agent`/`task`/`step` are internal opaque ids
  // (`tool` above is reused as the tool NAME); `count` is the cumulative tool-call
  // counter within the attempt; `phase` (shared field above) is 'calling-tool' |
  // 'writing' for this kind.
  agent?: string
  task?: string
  step?: string
  count?: number
  severity?: string
}

export interface OfficeMessage {
  seq: number
  ts: string
  author: string
  kind: OfficeEventKind
  body: OfficeEventBody
  /** Workroom the event originally happened in. Equal to the stream's own room for a
   *  native row; on the aggregated `office` stream it names the source workroom — most
   *  projected bodies carry no room/task field, so this is the only attribution. */
  source_room_id: string
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
  actor?: string | null // v46: agent that performed the action (may differ from agent_id log owner)
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

// v33 P1: Connections screen — presence-only key state, never a secret value.
export interface ConnectionKeyState {
  name: string
  set: boolean
}

export interface ConnectionCard {
  id: string
  label: string
  ok: boolean
  detail: string
  hint: string
  note: string
  keys: ConnectionKeyState[]
}

export interface ConnectionsPayload {
  cards: ConnectionCard[]
  needs_restart: boolean
}

export interface ConnectionKeysResult {
  ok: boolean
  written: string[]
  needs_restart: boolean
}

export interface RestartResult {
  ok: boolean
  managed: boolean
  message: string
}

// v33 P3: outputs hub + team-task kanban board.
export interface OutputItem {
  kind: 'step' | 'file'
  task_id: string
  task_title: string
  room_id: string
  seq: number
  step_title: string
  agent_id: string
  ts: string
  name?: string
  size?: number
}

export interface OutputsPayload {
  items: OutputItem[]
  truncated: boolean
}

export interface TeamBoardCard {
  task_id: string
  title: string
  pic_id: string
  room_id: string
  status: string
  created_at: string
  steps_done: number
  steps_total: number
  steps_needs_shell?: number // v50: count of steps needing the deep_agent (Docker sandbox) tier
  // v58: vị trí trong hàng đợi coordinator (0 = tới lượt; ≥1 = xếp sau N việc; absent =
  // không trong hàng dispatchable). Ticker 1 hành-động/phút nên N ≈ số phút chờ.
  queue_position?: number
  // v88 P3: title of the first dead (failed/timeout) step on a `stalled` task — absent
  // when the stall came from an exhausted review round (no dead step) or the task is
  // not stalled at all.
  stalled_step?: string
}

export interface TeamBoardLane {
  id: string
  cards: TeamBoardCard[]
}

// v88 P3: one-click unstick + cancel — every action route returns the task's
// refreshed shape so the caller can repaint from one response.
export interface TeamTaskActionStep {
  step_id: string
  title: string
  status: string
  step_type: string
  assigned_to: string
}

export interface TeamTaskActionResult {
  task_id: string
  title: string
  status: string
  pic_id: string
  room_id: string
  steps: TeamTaskActionStep[]
}

// v88 P3: the bounded scope enum an approve/reject decision may carry — "once" (no
// standing rule) or the two learned-rule scopes the gateway's rule store accepts.
export type ApprovalScope = 'once' | 'always' | 'deny'

// v50: per-task cost breakdown — one entry per step-attempt + task totals.
export interface TeamTaskCostStep {
  step_id?: string
  agent_id?: string
  engine?: string
  status?: string
  step_type?: string
  cost_usd?: number | null
  cost_source?: string
  input_tokens?: number | null
  output_tokens?: number | null
  duration_ms?: number | null
}

export interface TeamTaskCostPayload {
  task_id: string
  steps: TeamTaskCostStep[]
  total_cost_usd: number
  total_input_tokens: number
  total_output_tokens: number
}

export interface TeamBoardPayload {
  lanes: TeamBoardLane[]
}

// v82: persisted sprint/team routing decision — fields empty when the task predates
// route_json or is unknown (the endpoint never 404s).
export interface TeamTaskRoutePayload {
  task_id: string
  mode: string
  source: string
  reason: string
}

// v82: store-side task metrics (wall-clock includes queue wait — the CEO's experienced
// latency). 404 for unknown tasks, unlike /route.
export interface TeamTaskMetricStep {
  seq: number
  step_type: string
  status: string
  cost_usd: number
  seconds: number | null
}

export interface TeamTaskMetricsPayload {
  task_id: string
  mode: string
  status: string
  wall_clock_seconds: number | null
  wall_clock_text: string
  cost_usd: number
  step_count: number
  content_steps: number
  review_steps: number
  rework_steps: number
  steps: TeamTaskMetricStep[]
}

// v33 P4: clarify — agent questions awaiting the CEO's answer.
export interface ClarifyQuestion {
  id: number
  agent_id: string
  task_id: string
  question: string
  options: string[]
  asked_at: string
  expires_at: string
}

export interface ClarifyPendingPayload {
  questions: ClarifyQuestion[]
}

// v36 P3: template config version-pin.
export interface TemplateStatusRow {
  agent_id: string
  role: string
  applied_version: number
  latest_version: number
  upgradable: boolean
}

export interface TemplateStatusPayload {
  agents: TemplateStatusRow[]
}

export interface TemplateUpgradePreview {
  role: string
  applied_version: number
  latest_version: number
  apply: Record<string, unknown>
  keep: string[]
  unchanged: string[]
}

export interface TemplateUpgradeResult extends TemplateUpgradePreview {
  backup: string
}

// --- Dual-lens P3: read-only observability payloads ---

export interface FleetBudgetAgent {
  agent_id: string
  spent_usd: number
  cap_usd: number
  ratio: number
}

export interface FleetBudgetPayload {
  agents: FleetBudgetAgent[]
  total_spent_usd: number
  total_cap_usd: number
  ratio: number
}

// One per-step-attempt telemetry row (v26 captures table, verbatim column names).
export interface CaptureRow {
  attempt_id: string
  task_id: string
  step_id: string
  agent_id: string
  engine: string
  status: string
  step_type: string
  review_round: number
  cost_usd: number | null
  cost_source: string
  input_tokens: number | null
  output_tokens: number | null
  started_at: string
  ended_at: string
  duration_ms: number | null
  error: string
  ts: string
}

export interface CapturesPayload {
  captures: CaptureRow[]
}

// v54 P4b: one per-criterion review row (`{criterion, passed, note}`, the rubric
// `team_task_check_prompt` produces) — persisted only on a review step's own capture row.
export interface CaptureCriterion {
  criterion: string
  passed: boolean
  note: string
}

// The DETAIL endpoint's shape (`GET /api/captures/{attempt_id}`): every `CaptureRow`
// field plus `criteria` — `null` for a non-review attempt or a pre-P4b row (never `[]`,
// which would misreport "reviewed, zero criteria"). The LIST endpoint never returns this
// field at all, so it lives on its own type rather than widening `CaptureRow`.
export interface CaptureDetail extends CaptureRow {
  criteria: CaptureCriterion[] | null
}

export interface HistorySearchHit {
  excerpt: string
  source: 'step' | 'audit'
  ref: string
  agent_id: string
  ts: string
}

export interface HistorySearchPayload {
  hits: HistorySearchHit[]
}

// v54: `/api/schedule/upcoming` — top-10 soonest cron fires fleet-wide.
export interface ScheduleItem {
  agent_id: string
  kind: string
  next_ts: string
  label: string
}

export interface SchedulePayload {
  items: ScheduleItem[]
}
