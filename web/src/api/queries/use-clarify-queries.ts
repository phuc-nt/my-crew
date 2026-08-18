// Clarify slice — questions an agent is blocked on until the CEO answers.
//
// Mirrors use-approvals-queries.ts: one query key for the whole fleet, so the chat
// context pane and the Duyệt page read the same cache and an answer given in one
// updates the other. The key is the same one the SSE bridge invalidates on a `consult`
// event (see sse-invalidation-bridge.ts), which is how a new question appears without
// anyone polling.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

/** Backend error text for a question already answered elsewhere (e.g. a Telegram tap). */
const ALREADY_ANSWERED = 'đã được trả lời'

/**
 * True when a failed answer means "someone else got there first" rather than a real
 * error. The backend is first-answer-wins and returns 409 in that case; the right
 * response is to refresh the list, not to show the CEO a failure.
 *
 * Matches the API's own Vietnamese error text — this is server data, not UI copy, so it
 * stays literal regardless of the interface language.
 */
export function isAlreadyAnswered(error: unknown): boolean {
  return error instanceof Error && error.message.includes(ALREADY_ANSWERED)
}

export function usePendingClarify() {
  return useQuery({
    queryKey: queryKeys.clarify.pending(),
    queryFn: () => api.getClarifyPending(),
  })
}

export function useAnswerClarify() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, answer }: { id: number; answer: string }) => api.answerClarify(id, answer),
    // Settled, not success: a 409 (answered elsewhere) leaves a row that is no longer
    // pending, so the list must refetch on failure too or it keeps showing a dead question.
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.clarify.pending() })
    },
  })
}
