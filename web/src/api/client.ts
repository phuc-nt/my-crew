// The single fetch surface for the SPA. Every view imports these — no view calls fetch
// directly. Centralizes the base URL, JSON parsing, and error mapping. The base is relative
// (''), so requests hit the same origin whether served by FastAPI static or the vite dev proxy.
import type {
  AgentStatus,
  AgentSummary,
  AuditPayload,
  AutomationPayload,
  CostPayload,
  MemoryPayload,
  RunsPayload,
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

export const api = {
  getAgents: () => request<AgentSummary[]>('/api/agents'),
  getAgentStatus: (id: string) => request<AgentStatus>(`/api/agents/${id}/status`),
  getRuns: (id: string) => request<RunsPayload>(`/api/runs/${id}`),
  getCost: (id: string) => request<CostPayload>(`/api/cost/${id}`),
  getMemory: (id: string, audience = 'internal') =>
    request<MemoryPayload>(`/api/memory/${id}?audience=${encodeURIComponent(audience)}`),
  getAutomation: (id: string) => request<AutomationPayload>(`/api/automation/${id}`),
  getAudit: (id: string) => request<AuditPayload>(`/api/audit/${id}`),
}

export { ApiError }
