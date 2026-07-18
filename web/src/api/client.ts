// The single fetch surface for the SPA. Every view imports these — no view calls fetch
// directly. Centralizes the base URL, JSON parsing, and error mapping. The base is relative
// (''), so requests hit the same origin whether served by FastAPI static or the vite dev proxy.
import type {
  AssignPreviewPayload,
  AssignStaffPayload,
  CaptureRow,
  CapturesPayload,
  CoordinatorHealthPayload,
  FleetBudgetPayload,
  HistorySearchPayload,
  UnregisteredProfilesPayload,
  RoomArtifactsPayload,
  StepArtifactPayload,
  RoomChatPayload,
  WorkroomsPayload,
  AgentStatus,
  AgentSummary,
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
  DeleteAgentResult,
  EnabledResult,
  AgentCompanyDocsPayload,
  CompanyActivityPayload,
  CompanyDoc,
  IntegrationHealthPayload,
  KnowledgePayload,
  MemoryPayload,
  SkillsPayload,
  OfficeRoomsPayload,
  OpsChatAvailable,
  OutputsPayload,
  TemplateStatusPayload,
  TemplateUpgradePreview,
  TemplateUpgradeResult,
  TeamBoardPayload,
  TeamTaskCostPayload,
  OpsChatCommand,
  OpsChatReply,
  PacksPayload,
  RunsPayload,
  StaffTemplatesPayload,
  TasksPayload,
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

// v6 M16: when any call returns 401 the session expired/absent — notify the app shell so it
// can show the login screen instead of a broken view. A view can register one handler.
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

// v9 P1: map an HTTP status to a friendly Vietnamese line for a low-tech CEO, instead of the
// raw "500 Internal Server Error for /api/…". A backend-provided `detail` is appended small.
function friendlyError(status: number, detail?: string): string {
  const base =
    status >= 500
      ? 'Máy chủ đang gặp lỗi, thử lại sau.'
      : status === 404
        ? 'Không tìm thấy dữ liệu.'
        : status === 403
          ? 'Bạn không có quyền làm việc này.'
          : `Có lỗi (${status}).`
  return detail && detail !== `${status}` ? `${base} (${detail})` : base
}

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (res.status === 401) {
    onUnauthorized?.()
    throw new ApiError(401, 'chưa đăng nhập')
  }
  if (!res.ok) {
    throw new ApiError(res.status, friendlyError(res.status))
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
    throw new ApiError(401, 'chưa đăng nhập')
  }
  if (!res.ok) {
    // Prefer the backend's exact detail (e.g. a config-validation message the CEO should see),
    // else a friendly Vietnamese line for the status.
    let detail = ''
    try {
      const j = (await res.json()) as { detail?: string }
      if (j.detail) detail = j.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail || friendlyError(res.status))
  }
  return (await res.json()) as T
}

export const api = {
  getAgents: () => request<AgentSummary[]>('/api/agents'),
  getAgentStatus: (id: string) => request<AgentStatus>(`/api/agents/${id}/status`),
  getRuns: (id: string) => request<RunsPayload>(`/api/runs/${id}`),
  getCost: (id: string) => request<CostPayload>(`/api/cost/${id}`),
  getMemory: (id: string, audience = 'internal') =>
    request<MemoryPayload>(`/api/memory/${id}?audience=${encodeURIComponent(audience)}`),
  getAutomation: (id: string) => request<AutomationPayload>(`/api/automation/${id}`),
  getAudit: (id: string) => request<AuditPayload>(`/api/audit/${id}`),

  // --- ops (S4): write surfaces — all go through the existing gateway-routed endpoints ---
  getApprovals: (id: string) => request<ApprovalsPayload>(`/api/agents/${id}/approvals`),
  approve: (id: string, approvalId: number) =>
    post<ApprovalsPayload>(`/api/agents/${id}/approvals/${approvalId}/approve`),
  reject: (id: string, approvalId: number) =>
    post<ApprovalsPayload>(`/api/agents/${id}/approvals/${approvalId}/reject`),
  getConfig: (id: string) => request<ConfigPayload>(`/api/agents/${id}/config`),
  saveProfile: (id: string, text: string) =>
    post<{ saved: string }>(`/api/agents/${id}/config/profile`, { text }),
  saveMarkdown: (id: string, which: 'soul' | 'project', text: string) =>
    post<{ saved: string }>(`/api/agents/${id}/config/${which}`, { text }),
  triggerRun: (id: string, params: { kind: string; audience: string; dry_run: boolean }) =>
    post<TriggerResult>(`/api/agents/${id}/trigger`, params),

  // --- admin (v3 M7): create wizard, team lifecycle, integration health ---
  getPacks: () => request<PacksPayload>('/api/packs'),
  createAgent: (spec: CreateAgentSpec) => post<CreateAgentResult>('/api/agents/create', spec),
  setAgentEnabled: (id: string, enabled: boolean) =>
    mutate<EnabledResult>(`/api/agents/${id}/enabled`, 'PATCH', { enabled }),
  deleteAgent: (id: string) => mutate<DeleteAgentResult>(`/api/agents/${id}`, 'DELETE'),
  // v18: recovery for profiles that exist on disk but fell out of the registry
  getUnregisteredProfiles: () =>
    request<UnregisteredProfilesPayload>('/api/agents/unregistered'),
  registerExistingProfile: (id: string) =>
    post<{ id: string; registered: boolean }>(`/api/agents/${id}/register`, {}),
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
  // v33 P4: clarify — agent questions the CEO answers (buttons or free text).
  getClarifyPending: () => request<ClarifyPendingPayload>('/api/clarify/pending'),
  answerClarify: (id: number, answer: string) =>
    post<{ ok: boolean; id: number }>(`/api/clarify/${id}/answer`, { answer }),
  getTeamAlerts: () => request<TeamAlertsPayload>('/api/team/alerts'),
  // Company identity (config-only) + staff-template picker.
  getCompany: () => request<CompanyPayload>('/api/company'),
  saveCompany: (
    name: string, coordinatorId: string | null, teamTaskCapUsd?: number,
    teamTaskAutoConfirm?: boolean,
  ) =>
    post<CompanyPayload>('/api/company', {
      name,
      coordinator_id: coordinatorId,
      ...(teamTaskCapUsd !== undefined ? { team_task_cap_usd: teamTaskCapUsd } : {}),
      // omitted ⇒ backend preserves the current value (load-modify-save, v15 F7)
      ...(teamTaskAutoConfirm !== undefined ? { team_task_auto_confirm: teamTaskAutoConfirm } : {}),
    }),
  // v15 office composer — thin wrappers over the assign command's preview/confirm/cancel.
  getAssignableStaff: () => request<AssignStaffPayload>('/api/office/assign/staff'),
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
  getCoordinatorHealth: () => request<CoordinatorHealthPayload>('/api/health/coordinator'),
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
    request<CaptureRow>(`/api/captures/${encodeURIComponent(attemptId)}`),
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
  assignConfirm: (taskId: string, planHash: string) =>
    post<{ text: string }>('/api/office/assign/confirm', { task_id: taskId, plan_hash: planHash }),
  assignCancel: (taskId: string) =>
    post<{ ok: boolean }>('/api/office/assign/cancel', { task_id: taskId }),
  getStaffTemplates: () => request<StaffTemplatesPayload>('/api/staff-templates'),
  // v32: one-click create from a template + whole-crew bootstrap (server builds the spec).
  createFromTemplate: (roleId: string, agentId?: string) =>
    post<CreateFromTemplateResult>('/api/agents/create-from-template', {
      role_id: roleId,
      ...(agentId ? { agent_id: agentId } : {}),
    }),
  getCrewPreview: () => request<CrewPreview>('/api/crew/preview'),
  createCrew: () => post<CrewCreateResult>('/api/crew/create'),
  // v6 M14b: CEO chat-ops — same engine + shared conversation as the Telegram DM path.
  opsChatAvailable: () => request<OpsChatAvailable>('/api/ops/chat/available'),
  opsChat: (message: string) => post<OpsChatReply>('/api/ops/chat', { message }),
  getOpsChatCommands: () =>
    request<{ commands: OpsChatCommand[] }>('/api/ops/chat/commands'),
  // v6 M15b: assigned-tasks board.
  getTasks: () => request<TasksPayload>('/api/tasks'),
  cancelTask: (agentId: string, taskId: number) =>
    post<{ status: string }>(`/api/tasks/${encodeURIComponent(agentId)}/${taskId}/cancel`),
  // v6 M16: auth.
  getMe: () => request<{ authenticated: boolean; user?: string; auth?: string }>('/api/me'),
  login: (username: string, password: string) =>
    post<{ ok: boolean }>('/api/login', { username, password }),
  logout: () => post<{ ok: boolean }>('/api/logout'),
  // v7 M17: first-run setup wizard.
  setupStatus: () =>
    request<{ completed: boolean; keys?: Record<string, boolean> }>('/api/setup/status'),
  setupEnv: (values: Record<string, string>) =>
    post<{ ok: boolean; written: string[] }>('/api/setup/env', values),
  setupTest: (group: string) =>
    post<{ group: string; ok: boolean; detail: string; hint: string }>(`/api/setup/test/${group}`),
  setupFinish: (username: string, password: string) =>
    post<{ ok: boolean; restarting: boolean; message: string }>('/api/setup/finish', {
      username,
      password,
    }),
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
  getCompanyDoc: (slug: string) =>
    request<CompanyDoc>(`/api/company-docs/${encodeURIComponent(slug)}`),
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
  // v12 M29: office group-chat room — the room list; the timeline itself streams via
  // raw EventSource (see hooks/use-office-stream.ts), not this request() helper.
  getOfficeRooms: () => request<OfficeRoomsPayload>('/api/office/rooms'),
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
