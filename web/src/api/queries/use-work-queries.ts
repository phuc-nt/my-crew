// Work slice — the task board, one task's detail reads, the outputs index, and the
// fleet schedule.
//
// The board is NOT polled. It reads the same `tasks.board()` key the SSE→invalidate
// bridge pushes to on every progress kind (assignment/milestone/review/step_status/
// handoff), so a task moving lane repaints from the live stream. The old view polled
// on mount only and went stale the moment anything happened.
import { useQuery } from '@tanstack/react-query'
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
