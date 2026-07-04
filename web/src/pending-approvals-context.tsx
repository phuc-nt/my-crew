// v7 M20: share ONE pending-approvals aggregate across the app so the nav badge (Layout) and
// the chat alert chip (Chat) don't each run their own 30s fan-out over the fleet. Both read
// this context; the single provider polls once. (Review H1 — avoid the /chat double-poll.)
import { type ReactNode, createContext, useContext } from 'react'
import { type AgentApproval, usePendingApprovals } from './hooks/use-pending-approvals'

interface PendingApprovalsValue {
  items: AgentApproval[]
  count: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

const Ctx = createContext<PendingApprovalsValue | null>(null)

export function PendingApprovalsProvider({ children }: { children: ReactNode }) {
  const value = usePendingApprovals()
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

const EMPTY: PendingApprovalsValue = {
  items: [],
  count: 0,
  loading: false,
  error: null,
  refresh: async () => {},
}

// Read the shared aggregate. Outside the provider (e.g. a component rendered in isolation in
// a test) it returns an inert empty value — never a second fan-out, and no conditional hook.
export function useSharedPendingApprovals(): PendingApprovalsValue {
  return useContext(Ctx) ?? EMPTY
}
