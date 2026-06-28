// Selected-agent state shared across views. Kept minimal (React context + the agent list
// fetched once) — no state library. Views read `useAgent()` to know which agent to query.
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api/client'
import type { AgentSummary } from './types'

interface AgentCtx {
  agents: AgentSummary[]
  selected: string | null
  setSelected: (id: string) => void
  loading: boolean
  error: string | null
}

const Ctx = createContext<AgentCtx | null>(null)

export function AgentProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getAgents()
      .then((list) => {
        setAgents(list)
        setSelected((cur) => cur ?? list[0]?.id ?? null)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed to load agents'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Ctx.Provider value={{ agents, selected, setSelected, loading, error }}>
      {children}
    </Ctx.Provider>
  )
}

export function useAgent(): AgentCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAgent must be used within AgentProvider')
  return ctx
}
