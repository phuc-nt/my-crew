// Approvals slice — the fleet-wide pending queue.
//
// One query for the whole fleet, shared by every surface that shows the queue (the
// chat context pane and the work hub). Because they read the SAME key, approving in
// one place updates the other with no cross-component wiring: the mutation
// invalidates the key both are subscribed to.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

export function usePendingApprovals() {
  return useQuery({
    queryKey: queryKeys.approvals.pending(),
    queryFn: () => api.getPendingApprovals(),
  })
}

/** Approve/reject stay per-agent routes, so each row carries the agent it belongs to. */
export function useApprovalDecision() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      agentId,
      approvalId,
      decision,
    }: {
      agentId: string
      approvalId: number
      decision: 'approve' | 'reject'
    }) =>
      decision === 'approve'
        ? api.approve(agentId, approvalId)
        : api.reject(agentId, approvalId),
    onSettled: () => {
      // Settled, not success: a failed approve leaves the row pending (the gateway
      // reverts it), so the queue still has to refetch or the UI would show a decision
      // that never happened.
      void client.invalidateQueries({ queryKey: queryKeys.approvals.pending() })
    },
  })
}
