// Control-plane slice — the fleet overview strip and the `/health` version poll.
//
// Both are polls, not SSE: the overview is a cross-store aggregate no single event
// names completely (the bridge still nudges it on work events), and `/health` is public
// and cheap, so a 60 s poll is the whole "new version installed" detector.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

export const OVERVIEW_POLL_MS = 30_000
export const HEALTH_POLL_MS = 60_000

export function useControlPlaneOverview() {
  return useQuery({
    queryKey: queryKeys.system.controlPlaneOverview(),
    queryFn: () => api.getControlPlaneOverview(),
    refetchInterval: OVERVIEW_POLL_MS,
  })
}

/** `pollMs` is a parameter so a test can tick it without faking timers app-wide. */
export function useHealth(pollMs: number = HEALTH_POLL_MS) {
  return useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: () => api.getHealth(),
    refetchInterval: pollMs,
    // A tab left open overnight should still notice the morning's install.
    refetchIntervalInBackground: true,
    retry: false,
  })
}
