// The single fetch surface for the SPA. Every view imports these — no view calls fetch
// directly. Centralizes the base URL, JSON parsing, and error mapping. The base is relative
// (''), so requests hit the same origin whether served by FastAPI static or the vite dev proxy.
//
// v53 i18n: friendlyError()/request()/mutate() sit below any component/hook context (no `t`
// to thread through ~60 API call sites), so they read the language directly from localStorage
// (same key/fallback as language-context.tsx's readStored()) and look up DICT[lang] — this
// keeps friendlyError/auth messages consistent with whatever the user has picked, without a
// React dependency at this layer.
import { DICT } from '../i18n/dictionary'
import type { Language } from '../i18n/dictionary'
import { fetchCached, invalidateCached } from '../lib/api-cache'
import type {
  AssignPreviewPayload,
  AssignStaffPayload,
  CaptureDetail,
  CapturesPayload,
  CoordinatorHealthPayload,
  FleetBudgetPayload,
  HistorySearchPayload,
  UnregisteredProfilesPayload,
  RoomArtifactsPayload,
  StepArtifactPayload,
  StepTranscriptPayload,
  RoomChatPayload,
  WorkroomsPayload,
  AgentBand,
  AgentBandResult,
  AgentProfileSettingsPatch,
  AgentProfileSettingsPatchResult,
  AgentProfileSettingsPayload,
  AgentSafetyPayload,
  AgentStatus,
  AgentSummary,
  ApprovalScope,
  ApprovalsPayload,
  ClarifyPendingPayload,
  AuditPayload,
  AutomationPayload,
  CompanyPayload,
  ConfigPayload,
  ConnectionKeysResult,
  ConnectionsPayload,
  RestartResult,
  CostPayload,
  CreateAgentResult,
  CreateAgentSpec,
  CreateFromTemplateResult,
  CrewCreateResult,
  CrewPreview,
  CrewsPayload,
  DeleteAgentResult,
  EnabledResult,
  AgentCompanyDocsPayload,
  CompanyActivityPayload,
  CompanyDoc,
  IntegrationHealthPayload,
  KnowledgePayload,
  MemoryPayload,
  ModelCatalogPayload,
  SkillsPayload,
  OpsChatAvailable,
  OutputsPayload,
  PendingApprovalsIndex,
  TemplateStatusPayload,
  TemplateUpgradePreview,
  TemplateUpgradeResult,
  TeamBoardPayload,
  TeamTaskActionResult,
  TeamTaskCostPayload,
  TeamTaskMetricsPayload,
  TeamTaskRoutePayload,
  OpsChatCommand,
  OpsChatReply,
  PacksPayload,
  RunsPayload,
  SchedulePayload,
  StaffTemplatesPayload,
  TeamAlertsPayload,
  TriggerResult,
} from '../types'

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

// Prefer the backend's exact detail (e.g. a config-validation message the CEO should
// see), else a friendly line for the status. Shared by every read/write path so GET
// errors carry the same detail writes always did.
async function apiErrorFrom(res: Response): Promise<ApiError> {
  let detail = ''
  try {
    const j = (await res.json()) as { detail?: string }
    if (j.detail) detail = j.detail
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail || friendlyError(res.status))
}

// v6 M16: when any call returns 401 the session expired/absent — notify the app shell so it
// can show the login screen instead of a broken view. A view can register one handler.
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

// Same storage key/fallback as language-context.tsx's readStored() — this module has no
// React context, so it reads the persisted preference directly.
function currentLang(): Language {
  try {
    return localStorage.getItem('ui-lang') === 'en' ? 'en' : 'vi'
  } catch {
    return 'vi'
  }
}

// v9 P1: map an HTTP status to a friendly line for a low-tech CEO, instead of the raw
// "500 Internal Server Error for /api/…". Backend `detail` handling lives in
// `apiErrorFrom` — this is only the no-detail fallback.
function friendlyError(status: number): string {
  const dict = DICT[currentLang()]
  return status >= 500
    ? dict['api.friendlyServerError']
    : status === 404
      ? dict['api.friendlyNotFound']
      : status === 403
        ? dict['api.friendlyForbidden']
        : dict['api.friendlyGeneric'].replaceAll('{status}', String(status))
}

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (res.status === 401) {
    onUnauthorized?.()
    throw new ApiError(401, DICT[currentLang()]['api.notLoggedIn'])
  }
  if (!res.ok) {
    throw await apiErrorFrom(res)
  }
  return (await res.json()) as T
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return mutate<T>(path, 'POST', body)
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  return mutate<T>(path, 'PUT', body)
}

async function mutate<T>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401 && path !== '/api/login') {
    onUnauthorized?.()
    throw new ApiError(401, DICT[currentLang()]['api.notLoggedIn'])
  }
  if (!res.ok) {
    throw await apiErrorFrom(res)
  }
  return (await res.json()) as T
}

// A mutation that changes the roster must invalidate the cached reads over it, or
// the refresh a view fires right after (Team, Setup, wizard) can be served stale.
function withRosterInvalidate<T>(p: Promise<T>): Promise<T> {
  return p.then((v) => {
    invalidateCached('agents')
    invalidateCached('assign-staff')
    return v
  })
}

export const api = {
  // Cached (v82): fetched by several components on the same mount — dedupe + short
  // TTL via lib/api-cache. Agent mutations below invalidate 'agents'.
  getAgents: () => fetchCached('agents', () => request<AgentSummary[]>('/api/agents')),
  getAgentStatus: (id: string) => request<AgentStatus>(`/api/agents/${id}/status`),
  getRuns: (id: string) => request<RunsPayload>(`/api/runs/${id}`),
  getCost: (id: string) => request<CostPayload>(`/api/cost/${id}`),
  getMemory: (id: string, audience = 'internal') =>
    request<MemoryPayload>(`/api/memory/${id}?audience=${encodeURIComponent(audience)}`),
  getAutomation: (id: string) => request<AutomationPayload>(`/api/automation/${id}`),
  getAudit: (id: string) => request<AuditPayload>(`/api/audit/${id}`),
  // v87 P2: per-agent dry-run visibility + toggle. PATCH writes through profile_patch
  // (comment-preserving) and is effective on the agent's next scheduled tick / triggered
  // run — both dispatch paths re-read profile.yaml fresh, so no restart is required.
  getAgentSafety: (id: string) => request<AgentSafetyPayload>(`/api/agents/${id}/safety`),
  setAgentDryRun: (id: string, dryRun: boolean) =>
    mutate<AgentSafetyPayload>(`/api/agents/${id}/safety`, 'PATCH', { dry_run: dryRun }),

  // v88 P4: structured config form — name/model/model_chain/budget cap/schedule, all
  // written through the comment-preserving profile_patch (see AgentProfileSettingsPatch).
  getAgentProfileSettings: (id: string) =>
    request<AgentProfileSettingsPayload>(`/api/agents/${id}/profile-settings`),
  patchAgentProfileSettings: (id: string, patch: AgentProfileSettingsPatch) =>
    mutate<AgentProfileSettingsPatchResult>(`/api/agents/${id}/profile-settings`, 'PATCH', patch),
  // Autonomy band — a BandStore side-effect, NOT a profile.yaml write.
  getAgentBand: (id: string) => request<AgentBandResult>(`/api/agents/${id}/band`),
  setAgentBand: (id: string, band: AgentBand, reason?: string) =>
    post<AgentBandResult>(`/api/agents/${id}/band`, { band, reason }),
  // Model dropdown suggestions from config/model_prices.yaml (fleet-wide, agent-independent).
  getModelCatalog: () => request<ModelCatalogPayload>('/api/agents/model-catalog'),

  // --- ops (S4): write surfaces — all go through the existing gateway-routed endpoints ---
  /** Every agent's pending approvals in one call. The queue is shown on more than
   *  one surface, so a per-agent fan-out was paid once per surface. */
  getPendingApprovals: () => request<PendingApprovalsIndex>('/api/approvals/pending'),
  // v88 P3: scope defaults to "once" (no standing rule) — "always"/"deny" also
  // teaches the gateway's rule store the same way the chat `duyệt ... luôn` path does.
  approve: (id: string, approvalId: number, scope: ApprovalScope = 'once') =>
    post<ApprovalsPayload>(`/api/agents/${id}/approvals/${approvalId}/approve`, { scope }),
  reject: (id: string, approvalId: number, scope: ApprovalScope = 'once') =>
    post<ApprovalsPayload>(`/api/agents/${id}/approvals/${approvalId}/reject`, { scope }),
  getConfig: (id: string) => request<ConfigPayload>(`/api/agents/${id}/config`),
  saveProfile: (id: string, text: string) =>
    post<{ saved: string }>(`/api/agents/${id}/config/profile`, { text }),
  saveMarkdown: (id: string, which: 'soul' | 'project', text: string) =>
    post<{ saved: string }>(`/api/agents/${id}/config/${which}`, { text }),
  triggerRun: (id: string, params: { kind: string; audience: string; dry_run: boolean }) =>
    post<TriggerResult>(`/api/agents/${id}/trigger`, params),

  // --- admin (v3 M7): create wizard, team lifecycle, integration health ---
  getPacks: () => request<PacksPayload>('/api/packs'),
  createAgent: (spec: CreateAgentSpec) =>
    withRosterInvalidate(post<CreateAgentResult>('/api/agents/create', spec)),
  setAgentEnabled: (id: string, enabled: boolean) =>
    withRosterInvalidate(mutate<EnabledResult>(`/api/agents/${id}/enabled`, 'PATCH', { enabled })),
  deleteAgent: (id: string) =>
    withRosterInvalidate(mutate<DeleteAgentResult>(`/api/agents/${id}`, 'DELETE')),
  // v18: recovery for profiles that exist on disk but fell out of the registry
  getUnregisteredProfiles: () =>
    request<UnregisteredProfilesPayload>('/api/agents/unregistered'),
  registerExistingProfile: (id: string) =>
    withRosterInvalidate(
      post<{ id: string; registered: boolean }>(`/api/agents/${id}/register`, {})),
  getIntegrationHealth: () => request<IntegrationHealthPayload>('/api/health/integrations'),
  // v36 P3: template config version-pin — badge + review-then-apply upgrade.
  getTemplateStatus: () => request<TemplateStatusPayload>('/api/agents/template-status'),
  previewTemplateUpgrade: (id: string) =>
    request<TemplateUpgradePreview>(`/api/agents/${id}/template-upgrade`),
  applyTemplateUpgrade: (id: string) =>
    post<TemplateUpgradeResult>(`/api/agents/${id}/template-upgrade`, {}),
  // v33 P1: Connections screen — presence-only reads, whitelisted key writes, restart.
  getConnections: () => request<ConnectionsPayload>('/api/connections'),
  putConnectionKeys: (updates: Record<string, string>) =>
    put<ConnectionKeysResult>('/api/connections/keys', { updates }),
  restartService: () => post<RestartResult>('/api/connections/restart', {}),
  // v33 P3: outputs hub (cross-room artifact index) + team-task kanban board.
  getOutputs: (agent?: string, days?: number) => {
    const q = new URLSearchParams()
    if (agent) q.set('agent', agent)
    if (days) q.set('days', String(days))
    const qs = q.toString()
    return request<OutputsPayload>(`/api/outputs${qs ? `?${qs}` : ''}`)
  },
  getTeamTaskBoard: () => request<TeamBoardPayload>('/api/team-tasks/board'),
  // v50: per-step cost + token breakdown for one task (read-only, allowlisted).
  getTeamTaskCost: (taskId: string) =>
    request<TeamTaskCostPayload>(`/api/team-tasks/${encodeURIComponent(taskId)}/cost`),
  getTeamTaskRoute: (taskId: string) =>
    request<TeamTaskRoutePayload>(`/api/team-tasks/${encodeURIComponent(taskId)}/route`),
  getTeamTaskMetrics: (taskId: string) =>
    request<TeamTaskMetricsPayload>(`/api/team-tasks/${encodeURIComponent(taskId)}/metrics`),
  // v88 P3: one-click unstick (retry/accept/drop a stalled step) + cancel a live
  // task — thin wrappers over `routes_team_task_actions.py`; every call returns the
  // refreshed task shape so a caller can repaint without a follow-up GET.
  retryStalledStep: (taskId: string, stepId: string) =>
    post<TeamTaskActionResult>(
      `/api/team-tasks/${encodeURIComponent(taskId)}/steps/${encodeURIComponent(stepId)}/retry`,
    ),
  acceptStalledResult: (taskId: string, stepId: string) =>
    post<TeamTaskActionResult>(
      `/api/team-tasks/${encodeURIComponent(taskId)}/steps/${encodeURIComponent(stepId)}/accept`,
    ),
  dropStalledStep: (taskId: string, stepId: string) =>
    post<TeamTaskActionResult>(
      `/api/team-tasks/${encodeURIComponent(taskId)}/steps/${encodeURIComponent(stepId)}/drop`,
    ),
  cancelTeamTask: (taskId: string) =>
    post<TeamTaskActionResult>(`/api/team-tasks/${encodeURIComponent(taskId)}/cancel`),
  // v33 P4: clarify — agent questions the CEO answers (buttons or free text).
  getClarifyPending: () => request<ClarifyPendingPayload>('/api/clarify/pending'),
  answerClarify: (id: number, answer: string) =>
    post<{ ok: boolean; id: number }>(`/api/clarify/${id}/answer`, { answer }),
  getTeamAlerts: () => request<TeamAlertsPayload>('/api/team/alerts'),
  // v54: rail "Sắp chạy" — top-N soonest cron fires fleet-wide (read-only).
  getScheduleUpcoming: () => request<SchedulePayload>('/api/schedule/upcoming'),
  // Company identity (config-only) + staff-template picker.
  getCompany: () => request<CompanyPayload>('/api/company'),
  saveCompany: (
    name: string, coordinatorId: string | null, teamTaskCapUsd?: number,
    teamTaskAutoConfirm?: boolean,
    // v88 P5-D: concurrency + autopilot opened up on this same route — kept as a
    // trailing options object rather than two more positional params (every existing
    // call site stays byte-compatible).
    extra?: { teamTaskConcurrency?: number; autopilot?: boolean },
  ) =>
    post<CompanyPayload>('/api/company', {
      name,
      coordinator_id: coordinatorId,
      ...(teamTaskCapUsd !== undefined ? { team_task_cap_usd: teamTaskCapUsd } : {}),
      // omitted ⇒ backend preserves the current value (load-modify-save, v15 F7)
      ...(teamTaskAutoConfirm !== undefined ? { team_task_auto_confirm: teamTaskAutoConfirm } : {}),
      ...(extra?.teamTaskConcurrency !== undefined
        ? { team_task_concurrency: extra.teamTaskConcurrency } : {}),
      ...(extra?.autopilot !== undefined ? { autopilot: extra.autopilot } : {}),
    }),
  // v15 office composer — thin wrappers over the assign command's preview/confirm/cancel.
  getAssignableStaff: () =>
    fetchCached('assign-staff', () => request<AssignStaffPayload>('/api/office/assign/staff')),
  assignPreview: (brief: string, roomId = '') =>
    post<AssignPreviewPayload>('/api/office/assign/preview', { brief, room_id: roomId }),
  // v16 workrooms
  getWorkrooms: () => request<WorkroomsPayload>('/api/office/workrooms'),
  roomChat: (roomId: string, message: string) =>
    post<RoomChatPayload>(`/api/office/rooms/${roomId}/chat`, { message }),
  roomConfirmAdjust: (roomId: string, taskId: string, amendmentId: string) =>
    post<{ text: string }>(`/api/office/rooms/${roomId}/chat/confirm-adjust`, {
      task_id: taskId, amendment_id: amendmentId,
    }),
  getCoordinatorHealth: () =>
    fetchCached('coordinator-health',
      () => request<CoordinatorHealthPayload>('/api/health/coordinator')),
  // Dual-lens P3: read-only observability (fleet budget / captures / history search).
  getFleetBudget: () => request<FleetBudgetPayload>('/api/budget'),
  getCaptures: (params?: { task_id?: string; agent?: string; since?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.task_id) q.set('task_id', params.task_id)
    if (params?.agent) q.set('agent', params.agent)
    if (params?.since) q.set('since', params.since)
    if (params?.limit) q.set('limit', String(params.limit))
    const qs = q.toString()
    return request<CapturesPayload>(`/api/captures${qs ? `?${qs}` : ''}`)
  },
  getCaptureDetail: (attemptId: string) =>
    request<CaptureDetail>(`/api/captures/${encodeURIComponent(attemptId)}`),
  searchHistory: (q: string, params?: { agent?: string; days?: number; limit?: number }) => {
    const usp = new URLSearchParams({ q })
    if (params?.agent) usp.set('agent', params.agent)
    if (params?.days) usp.set('days', String(params.days))
    if (params?.limit) usp.set('limit', String(params.limit))
    return request<HistorySearchPayload>(`/api/search?${usp.toString()}`)
  },
  // v17 artifact viewer (read-only)
  getRoomArtifacts: (roomId: string) =>
    request<RoomArtifactsPayload>(`/api/office/rooms/${roomId}/artifacts`),
  getStepArtifact: (taskId: string, seq: number) =>
    request<StepArtifactPayload>(`/api/office/tasks/${taskId}/steps/${seq}/artifact`),
  getStepTranscript: (taskId: string, seq: number) =>
    request<StepTranscriptPayload>(`/api/office/tasks/${taskId}/steps/${seq}/transcript`),
  assignConfirm: (taskId: string, planHash: string) =>
    post<{ text: string }>('/api/office/assign/confirm', { task_id: taskId, plan_hash: planHash }),
  assignCancel: (taskId: string) =>
    post<{ ok: boolean }>('/api/office/assign/cancel', { task_id: taskId }),
  getStaffTemplates: () => request<StaffTemplatesPayload>('/api/staff-templates'),
  // v32: one-click create from a template + whole-crew bootstrap (server builds the spec).
  createFromTemplate: (roleId: string, agentId?: string) =>
    withRosterInvalidate(
      post<CreateFromTemplateResult>('/api/agents/create-from-template', {
        role_id: roleId,
        ...(agentId ? { agent_id: agentId } : {}),
      })),
  // v71: crewId omitted ⇒ the server's default crew (office), same as pre-v71 clients.
  getCrews: () => request<CrewsPayload>('/api/crews'),
  getCrewPreview: (crewId?: string) =>
    request<CrewPreview>(`/api/crew/preview${crewId ? `?crew_id=${encodeURIComponent(crewId)}` : ''}`),
  createCrew: (crewId?: string) =>
    withRosterInvalidate(
      post<CrewCreateResult>(`/api/crew/create${crewId ? `?crew_id=${encodeURIComponent(crewId)}` : ''}`)),
  // v6 M14b: CEO chat-ops — same engine + shared conversation as the Telegram DM path.
  opsChatAvailable: () => request<OpsChatAvailable>('/api/ops/chat/available'),
  opsChat: (message: string) => post<OpsChatReply>('/api/ops/chat', { message }),
  getOpsChatCommands: () =>
    request<{ commands: OpsChatCommand[] }>('/api/ops/chat/commands'),
  // v6 M16: auth.
  getMe: () => request<{ authenticated: boolean; user?: string; auth?: string }>('/api/me'),
  login: (username: string, password: string) =>
    post<{ ok: boolean }>('/api/login', { username, password }),
  logout: () => post<{ ok: boolean }>('/api/logout'),
  // Đổi mật khẩu từ trong app. Thành công là đá luôn phiên hiện tại (BE xoay
  // session secret), nên nơi gọi phải đưa người dùng về màn đăng nhập.
  changePassword: (currentPassword: string, newPassword: string) =>
    post<{ ok: boolean; restarting: boolean; message: string }>(
      '/api/auth/change-password',
      { current_password: currentPassword, new_password: newPassword },
    ),
  // v7 M17: first-run setup wizard.
  setupStatus: () =>
    request<{ completed: boolean; keys?: Record<string, boolean> }>('/api/setup/status'),
  setupEnv: (values: Record<string, string>) =>
    post<{ ok: boolean; written: string[] }>('/api/setup/env', values),
  setupTest: (group: string) =>
    post<{ group: string; ok: boolean; detail: string; hint: string }>(`/api/setup/test/${group}`),
  setupFinish: (username: string, password: string) =>
    post<{ ok: boolean; restarting: boolean; restart_hint: string; message: string }>(
      '/api/setup/finish',
      { username, password },
    ),
  // v7 M18a: bind a Telegram bot to an agent (validates via getMe, no restart needed).
  bindTelegram: (agentId: string, token: string, chatIds: string[]) =>
    post<{ ok: boolean; bot_username?: string; env_name: string }>(
      `/api/agents/${encodeURIComponent(agentId)}/telegram`,
      { token, chat_ids: chatIds },
    ),
  telegramRecentChats: (agentId: string, token: string) =>
    post<{ chats: { id: string; name: string }[] }>(
      `/api/agents/${encodeURIComponent(agentId)}/telegram/updates`,
      { token },
    ),
  // v7 M18b: knowledge (SOUL/PROJECT) as a form ↔ markdown, + skills picker.
  getKnowledge: (agentId: string, doc: 'soul' | 'project') =>
    request<KnowledgePayload>(`/api/agents/${encodeURIComponent(agentId)}/knowledge/${doc}`),
  putKnowledgeForm: (agentId: string, doc: 'soul' | 'project', fields: Record<string, string>) =>
    put<{ ok: boolean }>(`/api/agents/${encodeURIComponent(agentId)}/knowledge/${doc}`, { fields }),
  putKnowledgeRaw: (agentId: string, doc: 'soul' | 'project', raw: string) =>
    put<{ ok: boolean }>(`/api/agents/${encodeURIComponent(agentId)}/knowledge/${doc}`, { raw }),
  getSkills: (agentId: string) =>
    request<SkillsPayload>(`/api/agents/${encodeURIComponent(agentId)}/skills`),
  putSkills: (agentId: string, names: string[]) =>
    put<{ ok: boolean; skills: string[] }>(
      `/api/agents/${encodeURIComponent(agentId)}/skills`,
      { names },
    ),
  // v7 M19: company-docs library + per-agent opt-in.
  listCompanyDocs: () => request<{ docs: CompanyDoc[] }>('/api/company-docs'),
  createCompanyDoc: (title: string, body: string, updated: string) =>
    post<CompanyDoc>('/api/company-docs', { title, body, updated }),
  updateCompanyDoc: (slug: string, title: string, body: string, updated: string) =>
    put<CompanyDoc>(`/api/company-docs/${encodeURIComponent(slug)}`, { title, body, updated }),
  deleteCompanyDoc: (slug: string) =>
    mutate<{ ok: boolean }>(`/api/company-docs/${encodeURIComponent(slug)}`, 'DELETE'),
  getAgentCompanyDocs: (agentId: string) =>
    request<AgentCompanyDocsPayload>(`/api/agents/${encodeURIComponent(agentId)}/company-docs`),
  putAgentCompanyDocs: (agentId: string, slugs: string[]) =>
    put<{ ok: boolean; company_docs: string[] }>(
      `/api/agents/${encodeURIComponent(agentId)}/company-docs`,
      { slugs },
    ),
  // v31 P1: fleet-wide activity timeline (audit + runs + team-step captures, allowlisted).
  getCompanyActivity: (params?: {
    limit?: number
    since?: string
    agent?: string
    verdict?: string
  }) => {
    const q = new URLSearchParams()
    if (params?.limit) q.set('limit', String(params.limit))
    if (params?.since) q.set('since', params.since)
    if (params?.agent) q.set('agent', params.agent)
    if (params?.verdict) q.set('verdict', params.verdict)
    const qs = q.toString()
    return request<CompanyActivityPayload>(`/api/company/activity${qs ? `?${qs}` : ''}`)
  },
}

export { ApiError }
