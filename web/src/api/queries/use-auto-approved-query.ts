// "Đã tự duyệt hôm nay" — the counterpart to the approvals queue.
//
// The queue says what the fleet is waiting on you for; this says what it decided WITHOUT
// asking, inside the trust limits you set. Showing only the first half would make the
// trust ladder invisible, which is exactly the setting a CEO most needs to sanity-check.
//
// There is no fleet-wide endpoint for it, so this fans out one /api/runs per agent. That
// is the same shape the old hook had, but on the query cache: one poll for every mounted
// consumer instead of one each, and it stops while the tab is hidden.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

export interface AutoApprovedRow {
  agentId: string
  kind: string
  timestamp: string
}

async function fetchAutoApproved(): Promise<AutoApprovedRow[]> {
  const today = new Date().toISOString().slice(0, 10)
  const agents = await api.getAgents()
  const per = await Promise.all(
    agents.map(async (a) => {
      try {
        const { runs } = await api.getRuns(a.id)
        return runs
          .filter((r) => r.auto_approved && (r.ts ?? '').slice(0, 10) === today)
          .map((r) => ({ agentId: a.id, kind: r.kind ?? '?', timestamp: r.ts ?? '' }))
      } catch {
        // One unreachable agent must not blank the whole block.
        return [] as AutoApprovedRow[]
      }
    }),
  )
  return per.flat()
}

export function useAutoApproved() {
  return useQuery({
    queryKey: queryKeys.approvals.autoApproved(),
    queryFn: fetchAutoApproved,
    staleTime: 60_000,
    refetchInterval: 60_000,
  })
}
