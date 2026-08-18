// Every context the app needs, in one place.
//
// The legacy `AgentProvider` / `PendingApprovalsProvider` are still here on purpose:
// the seven advanced views, Work, and office-unified all read them, so they stay until
// the last legacy view is deleted. Removing them early would crash those screens.
import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { AgentProvider } from '../agent-context'
import { createQueryClient } from '../api/queries/query-client'
import { PendingApprovalsProvider } from '../pending-approvals-context'

// Module scope, not component state: a client recreated on re-render would drop the
// whole cache and refetch every mounted query.
const queryClient = createQueryClient()

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AgentProvider>
        <PendingApprovalsProvider>{children}</PendingApprovalsProvider>
      </AgentProvider>
    </QueryClientProvider>
  )
}
