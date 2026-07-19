// v7 M20: aggregate pending-approval counts + items across ALL agents, client-side.
// No new backend route (red-team SCOPE-2): /api/agents lists agents and each agent's
// /approvals returns its pending items. We fan out and sum — fine for a small LAN fleet.
// The badge uses just the count; the Work page uses the full items (agent id attached).
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { DICT } from '../i18n/dictionary'
import type { ApprovalItem } from '../types'

export interface AgentApproval extends ApprovalItem {
  agentId: string
}

export function usePendingApprovals(pollMs = 30_000) {
  const [items, setItems] = useState<AgentApproval[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const agents = await api.getAgents()
      const per = await Promise.all(
        agents.map(async (a) => {
          try {
            const r = await api.getApprovals(a.id)
            return r.pending.map((p) => ({ ...p, agentId: a.id }))
          } catch {
            return [] as AgentApproval[] // one agent failing must not blank the whole board
          }
        }),
      )
      setItems(per.flat())
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : DICT.vi['usePendingApprovals.loadFailed'])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), pollMs)
    return () => clearInterval(t)
  }, [refresh, pollMs])

  return { items, count: items.length, loading, error, refresh }
}
