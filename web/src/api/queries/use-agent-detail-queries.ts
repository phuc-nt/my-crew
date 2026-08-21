// Per-agent detail slices. These used to be seven separate routes reading the agent from
// a global picker; here every one takes the id from the route, so a tab is a component
// and not a page.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import type { AgentBand, AgentProfileSettingsPatch } from '../../types'
import { queryKeys } from './query-keys'

const keys = {
  runs: (id: string) => ['agent-detail', 'runs', id] as const,
  cost: (id: string) => ['agent-detail', 'cost', id] as const,
  audit: (id: string) => ['agent-detail', 'audit', id] as const,
  memory: (id: string) => ['agent-detail', 'memory', id] as const,
  automation: (id: string) => ['agent-detail', 'automation', id] as const,
  config: (id: string) => ['agent-detail', 'config', id] as const,
  captures: (id: string) => ['agent-detail', 'captures', id] as const,
  safety: (id: string) => ['agent-detail', 'safety', id] as const,
  profileSettings: (id: string) => ['agent-detail', 'profile-settings', id] as const,
  modelCatalog: () => ['agent-detail', 'model-catalog'] as const,
  band: (id: string) => ['agent-detail', 'band', id] as const,
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

/** Effective dry-run for this agent (v87 P2) — the same resolution the worker runs
 *  with, not a re-derivation of the profile/env fallback rule on the client. */
export function useAgentSafety(id: string) {
  return useQuery({ queryKey: keys.safety(id), queryFn: () => api.getAgentSafety(id) })
}

/** Flip the per-agent dry-run override. Effective on the agent's next scheduled tick /
 *  triggered run (profile.yaml is re-read fresh by both dispatch paths) — no restart. */
export function useSetAgentDryRun(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (dryRun: boolean) => api.setAgentDryRun(id, dryRun),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.safety(id) }),
  })
}

/** v88 P4: current raw values (name/model/model_chain/budget cap/schedule) for the
 *  structured config form's pre-fill — the values actually written in profile.yaml,
 *  not the loader's env-resolved effective ones. */
export function useAgentProfileSettings(id: string) {
  return useQuery({
    queryKey: keys.profileSettings(id),
    queryFn: () => api.getAgentProfileSettings(id),
  })
}

/** Patch a subset of name/model/model_chain/budget_monthly_usd/schedule. Invalidates
 *  the profile-settings query (form re-reads current values) and the cost query
 *  (budget cap header) so both surfaces pick up the change without a page reload. */
export function usePatchAgentProfileSettings(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: AgentProfileSettingsPatch) => api.patchAgentProfileSettings(id, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.profileSettings(id) })
      void qc.invalidateQueries({ queryKey: keys.cost(id) })
    },
  })
}

/** Model ids known to config/model_prices.yaml — fleet-wide, agent-independent, so one
 *  cached query serves every agent's dropdown. */
export function useModelCatalog() {
  return useQuery({ queryKey: keys.modelCatalog(), queryFn: () => api.getModelCatalog() })
}

/** Current autonomy band — defaults to "normal" when never set (BandStore.get's own
 *  fail-direction default). */
export function useAgentBand(id: string) {
  return useQuery({ queryKey: keys.band(id), queryFn: () => api.getAgentBand(id) })
}

/** Set the agent's autonomy band (BandStore side-effect, not a profile.yaml write).
 *  Invalidates the band query (dropdown reflects the change) and the agent's status
 *  (no band field on it today, but keeps the header's other badges in sync on the
 *  same query cycle). */
export function useSetAgentBand(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ band, reason }: { band: AgentBand; reason?: string }) =>
      api.setAgentBand(id, band, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.band(id) })
      void qc.invalidateQueries({ queryKey: queryKeys.agents.status(id) })
    },
  })
}
