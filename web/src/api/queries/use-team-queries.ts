// Team slice — the roster, what can be created from it, and the per-agent overlays the
// roster paints on top (status, template-upgrade availability, fleet alerts).
//
// Every overlay here is deliberately failure-tolerant at the RENDER site rather than
// here: a roster that disappears because one agent's status 404'd is worse than a roster
// with one blank cell, so components read `data ?? fallback` instead of gating on error.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

/** Per-agent status (budget, pending approvals). Fanned out one query per row. */
export function useAgentStatus(agentId: string) {
  return useQuery({
    queryKey: queryKeys.agents.status(agentId),
    queryFn: () => api.getAgentStatus(agentId),
    // A row's status is an overlay on a roster that already rendered — a failure blanks
    // one cell, so retrying it repeatedly buys nothing.
    retry: false,
  })
}

/** Which agents have a newer template config than the one they were built from. */
export function useTemplateStatus() {
  return useQuery({
    queryKey: queryKeys.team.templateStatus(),
    queryFn: () => api.getTemplateStatus(),
    retry: false,
  })
}

/** Deterministic fleet alerts (budget near cap, stuck approvals, deny spikes). */
export function useTeamAlerts() {
  return useQuery({
    queryKey: queryKeys.team.alerts(),
    queryFn: () => api.getTeamAlerts(),
    retry: false,
  })
}

/** Profiles on disk that fell out of the registry — the recovery list. */
export function useUnregisteredProfiles() {
  return useQuery({
    queryKey: queryKeys.team.unregistered(),
    queryFn: () => api.getUnregisteredProfiles(),
    retry: false,
  })
}

export function useStaffTemplates() {
  return useQuery({
    queryKey: queryKeys.team.templates(),
    queryFn: () => api.getStaffTemplates(),
  })
}

export function useCrews() {
  return useQuery({
    queryKey: queryKeys.team.crews(),
    queryFn: () => api.getCrews(),
  })
}

/**
 * One crew's roster before it is created — the confirm step's content. `null` means the
 * DEFAULT crew (the banner's opening state), not "don't fetch": the banner has to know
 * whether a manifest exists at all before it can decide to render. No manifest ⇒ the
 * request fails ⇒ no banner, which is why this one does not retry.
 */
export function useCrewPreview(crewId: string | null) {
  return useQuery({
    queryKey: queryKeys.team.crewPreview(crewId ?? ''),
    queryFn: () => api.getCrewPreview(crewId ?? undefined),
    retry: false,
  })
}

export function useCompany() {
  return useQuery({
    queryKey: queryKeys.team.company(),
    queryFn: () => api.getCompany(),
  })
}

/**
 * Everything that changes the roster invalidates the same set, so a create/toggle/delete
 * from any surface repaints every other one. Kept as one helper because forgetting a key
 * here is invisible until a stale row confuses someone in production.
 */
function useRosterInvalidate() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.agents.all })
    void qc.invalidateQueries({ queryKey: queryKeys.team.all })
  }
}

/**
 * Pause/resume. The registry's `enabled` is NOT the last word: a profile can still veto
 * the agent, which the response reports as effective_enabled=false. Callers need that
 * distinction to explain why a Resume appeared to do nothing, so the mutation resolves
 * to the full result rather than a boolean.
 */
export function useSetAgentEnabled() {
  const invalidate = useRosterInvalidate()
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.setAgentEnabled(id, enabled),
    onSuccess: invalidate,
  })
}

export function useDeleteAgent() {
  const invalidate = useRosterInvalidate()
  return useMutation({
    mutationFn: (id: string) => api.deleteAgent(id),
    onSuccess: invalidate,
  })
}

export function useCreateFromTemplate() {
  const invalidate = useRosterInvalidate()
  return useMutation({
    mutationFn: ({ roleId, agentId }: { roleId: string; agentId?: string }) =>
      api.createFromTemplate(roleId, agentId),
    onSuccess: invalidate,
  })
}

export function useCreateCrew() {
  const invalidate = useRosterInvalidate()
  return useMutation({
    mutationFn: (crewId?: string) => api.createCrew(crewId),
    onSuccess: invalidate,
  })
}

export function useRegisterProfile() {
  const invalidate = useRosterInvalidate()
  return useMutation({
    mutationFn: (id: string) => api.registerExistingProfile(id),
    onSuccess: invalidate,
  })
}

export function useApplyTemplateUpgrade() {
  const invalidate = useRosterInvalidate()
  return useMutation({
    mutationFn: (id: string) => api.applyTemplateUpgrade(id),
    onSuccess: invalidate,
  })
}
