// Artifact slice — what a step actually produced, plus the recorder's raw log.
//
// Read-only and deliberately NOT wired into the SSE bridge: a finished step's artifact
// never changes, and the room index is opened on demand rather than kept warm. The one
// live edge (a step finishing while the drawer is open) is covered by the room query
// refetching when the drawer reopens.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

export function useRoomArtifacts(roomId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.artifacts.room(roomId),
    queryFn: () => api.getRoomArtifacts(roomId),
    enabled,
  })
}

export function useStepArtifact(taskId: string, seq: number | null) {
  return useQuery({
    queryKey: queryKeys.artifacts.step(taskId, seq ?? -1),
    queryFn: () => api.getStepArtifact(taskId, seq as number),
    enabled: seq !== null,
    // A step that produced nothing answers 404; retrying cannot change that.
    retry: false,
    // Finished output is immutable, so once fetched it never needs refreshing.
    staleTime: Infinity,
  })
}

export function useStepTranscript(taskId: string, seq: number | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.artifacts.transcript(taskId, seq ?? -1),
    queryFn: () => api.getStepTranscript(taskId, seq as number),
    enabled: enabled && seq !== null,
    retry: false,
    staleTime: Infinity,
  })
}
