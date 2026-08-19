// Every context the app needs, in one place.
//
// Only the query client remains. The pre-redesign `AgentProvider` (a global "selected
// agent") and `PendingApprovalsProvider` (a 30s fleet fan-out) are gone: the agent now
// rides in the route (`/team/:id`) and the approvals queue is one cached query that any
// surface can read by key.
import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '../api/queries/query-client'

// Module scope, not component state: a client recreated on re-render would drop the
// whole cache and refetch every mounted query.
const queryClient = createQueryClient()

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}
