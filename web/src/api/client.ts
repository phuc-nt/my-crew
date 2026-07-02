// The single fetch surface for the SPA. Every view imports these — no view calls fetch
// directly. Centralizes the base URL, JSON parsing, and error mapping. The base is relative
// (''), so requests hit the same origin whether served by FastAPI static or the vite dev proxy.
import type {
  AgentStatus,
  AgentSummary,
  ApprovalsPayload,
  AuditPayload,
  AutomationPayload,
  ConfigPayload,
  CostPayload,
  CreateAgentResult,
  CreateAgentSpec,
  DeleteAgentResult,
  EnabledResult,
  IntegrationHealthPayload,
  MemoryPayload,
  PacksPayload,
  RunsPayload,
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

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText} for ${path}`)
  }
  return (await res.json()) as T
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return mutate<T>(path, 'POST', body)
}

async function mutate<T>(path: string, method: 'POST' | 'PATCH' | 'DELETE', body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    // surface the backend's exact detail (e.g. the config validation message)
    let detail = `${res.status} ${res.statusText}`
    try {
      const j = (await res.json()) as { detail?: string }
      if (j.detail) detail = j.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
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
  getIntegrationHealth: () => request<IntegrationHealthPayload>('/api/health/integrations'),
}

export { ApiError }
