// Work slice — the task board, one task's detail reads, the outputs index, and the
// fleet schedule.
//
// The board is NOT polled. It reads the same `tasks.board()` key the SSE→invalidate
// bridge pushes to on every progress kind (assignment/milestone/review/step_status/
// handoff), so a task moving lane repaints from the live stream. The old view polled
// on mount only and went stale the moment anything happened.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

/** Every lane with its cards — the board's single request. */
export function useTaskBoard() {
  return useQuery({
    queryKey: queryKeys.tasks.board(),
    queryFn: () => api.getTeamTaskBoard(),
    // The stream is the refresh channel; a short staleTime only stops a remount from
    // re-fetching what the bridge just delivered.
    staleTime: 10_000,
  })
}

/**
 * One task's route decision (which coordinator mode picked it up and why). Never 404s
 * — a task that predates route_json answers with empty strings — so a failure here is
 * a real error and worth one retry's worth of nothing.
 */
export function useTaskRoute(taskId: string) {
  return useQuery({
    queryKey: [...queryKeys.tasks.detail(taskId), 'route'] as const,
    queryFn: () => api.getTeamTaskRoute(taskId),
    retry: false,
  })
}

/** Wall-clock, cost, and the content/review/rework split for one task. */
export function useTaskMetrics(taskId: string) {
  return useQuery({
    queryKey: [...queryKeys.tasks.detail(taskId), 'metrics'] as const,
    queryFn: () => api.getTeamTaskMetrics(taskId),
    retry: false,
  })
}

/**
 * The cross-room outputs index. Filters go in the key so switching agent or window
 * gets its own cache entry instead of refetching over the same one — and the bridge
 * invalidates `outputs.all`, which covers every filter combination at once.
 */
export function useOutputs(agent: string, days: number) {
  return useQuery({
    queryKey: [...queryKeys.outputs.list(), agent, days] as const,
    queryFn: () => api.getOutputs(agent || undefined, days || undefined),
  })
}

/** Top-N soonest cron fires fleet-wide. */
export function useScheduleUpcoming() {
  return useQuery({
    queryKey: queryKeys.schedule.upcoming(),
    queryFn: () => api.getScheduleUpcoming(),
    // Cron fires are minute-grained; refetching on every focus would be pure noise.
    staleTime: 60_000,
  })
}

// --- v88 P3: one-click unstick + cancel ------------------------------------------

// The action buttons live on two surfaces with different data sources: the board card
// reads queryKeys.tasks.board(), the task-detail page reads queryKeys.artifacts.room()
// (a room's artifacts carry the task's status + steps — what the stalled panel renders).
// A mutation therefore must invalidate BOTH the board and, when it fired from a room
// surface, that room's artifacts — else the detail page keeps painting the pre-action
// 'stalled' state and the buttons look like they did nothing. `roomId` is optional so
// the board-card caller (no room in scope, board query is enough) needs no change.
type StalledActionVars = { taskId: string; stepId: string; roomId?: string }

/** Shared invalidate for every stall/cancel mutation below: the board (lane may
 *  change), this one task's detail sub-queries, and the room's artifacts (the
 *  task-detail page's actual render source) when a room id is known. */
function useTeamTaskActionInvalidate() {
  const qc = useQueryClient()
  return (taskId: string, roomId?: string) => {
    void qc.invalidateQueries({ queryKey: queryKeys.tasks.board() })
    void qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) })
    if (roomId) void qc.invalidateQueries({ queryKey: queryKeys.artifacts.room(roomId) })
  }
}

/** Buy the stalled step one more attempt (rework round or re-dispatch). */
export function useRetryStalledStep() {
  const invalidate = useTeamTaskActionInvalidate()
  return useMutation({
    mutationFn: ({ taskId, stepId }: StalledActionVars) => api.retryStalledStep(taskId, stepId),
    onSettled: (_data, _err, { taskId, roomId }) => invalidate(taskId, roomId),
  })
}

/** Accept a review-stalled task's existing deliverable and let it complete. */
export function useAcceptStalledResult() {
  const invalidate = useTeamTaskActionInvalidate()
  return useMutation({
    mutationFn: ({ taskId, stepId }: StalledActionVars) => api.acceptStalledResult(taskId, stepId),
    onSettled: (_data, _err, { taskId, roomId }) => invalidate(taskId, roomId),
  })
}

/** Give up on a dead step so the rest of the DAG can finish without it. */
export function useDropStalledStep() {
  const invalidate = useTeamTaskActionInvalidate()
  return useMutation({
    mutationFn: ({ taskId, stepId }: StalledActionVars) => api.dropStalledStep(taskId, stepId),
    onSettled: (_data, _err, { taskId, roomId }) => invalidate(taskId, roomId),
  })
}

/** Cancel a live team task (open/running/stalled). */
export function useCancelTeamTask() {
  const invalidate = useTeamTaskActionInvalidate()
  return useMutation({
    mutationFn: ({ taskId }: { taskId: string; roomId?: string }) => api.cancelTeamTask(taskId),
    onSettled: (_data, _err, { taskId, roomId }) => invalidate(taskId, roomId),
  })
}
