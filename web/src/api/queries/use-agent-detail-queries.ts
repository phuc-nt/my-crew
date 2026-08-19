// Per-agent detail slices. These used to be seven separate routes reading the agent from
// a global picker; here every one takes the id from the route, so a tab is a component
// and not a page.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'

const keys = {
  runs: (id: string) => ['agent-detail', 'runs', id] as const,
  cost: (id: string) => ['agent-detail', 'cost', id] as const,
  audit: (id: string) => ['agent-detail', 'audit', id] as const,
  memory: (id: string) => ['agent-detail', 'memory', id] as const,
  automation: (id: string) => ['agent-detail', 'automation', id] as const,
  config: (id: string) => ['agent-detail', 'config', id] as const,
  captures: (id: string) => ['agent-detail', 'captures', id] as const,
}

export function useRuns(id: string) {
  return useQuery({ queryKey: keys.runs(id), queryFn: () => api.getRuns(id) })
}
export function useCost(id: string) {
  return useQuery({ queryKey: keys.cost(id), queryFn: () => api.getCost(id) })
}
export function useAudit(id: string) {
  return useQuery({ queryKey: keys.audit(id), queryFn: () => api.getAudit(id) })
}
/** Memory is internal-audience-only by the API's gate; the default audience is internal. */
export function useMemory(id: string) {
  return useQuery({ queryKey: keys.memory(id), queryFn: () => api.getMemory(id) })
}
export function useAutomation(id: string) {
  return useQuery({ queryKey: keys.automation(id), queryFn: () => api.getAutomation(id) })
}
export function useAgentConfig(id: string) {
  return useQuery({ queryKey: keys.config(id), queryFn: () => api.getConfig(id) })
}
/** Recorder captures narrowed to this agent — the per-run detail behind the run list. */
export function useAgentCaptures(id: string) {
  return useQuery({
    queryKey: keys.captures(id),
    queryFn: () => api.getCaptures({ agent: id, limit: 50 }),
    retry: false,
  })
}
