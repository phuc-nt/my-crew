// The one QueryClient for the app.
//
// `staleTime: 5s` matches the TTL the hand-rolled `lib/api-cache.ts` used, so
// navigation bursts absorb the same way they did before the migration — this is a
// swap of caching mechanism, not a change in how fresh the screens are.
//
// Refetch-on-focus is OFF: every screen that needs live data is already driven by
// the SSE→invalidate bridge, and a focus refetch on top of it would double the
// request rate on the exact screens that can least afford it (the office feed).
import { QueryClient } from '@tanstack/react-query'

export const DEFAULT_STALE_TIME_MS = 5_000

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME_MS,
        refetchOnWindowFocus: false,
        // A 401 flips the whole app back to the login screen (see `setUnauthorizedHandler`
        // in api/client.ts), so retrying it would only delay that redirect.
        retry: 1,
      },
    },
  })
}
