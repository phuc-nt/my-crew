// Shared request cache for the SPA's hot read endpoints (v82 perf pass).
//
// Two problems this solves, both measured on the /office mount:
//   1. In-flight dedupe — several components mounting together each fired their own
//      fetch for the SAME endpoint (/api/agents ×2+, /api/office/assign/staff ×2,
//      /api/health/coordinator ×2). Concurrent callers now share one promise.
//   2. Short TTL — a burst of navigations re-fetched data that cannot have changed
//      in the last few seconds. A small TTL absorbs the burst without any risk of
//      long-lived staleness.
//
// Deliberately NOT react-query: the app has exactly these patterns (dedupe, short
// TTL, explicit invalidate after a mutation), and this stays under ~80 lines. If a
// mutation-queue / stale-while-revalidate need ever appears, replace this module —
// callers only know `fetchCached`, so the exit path is narrow.

interface CacheEntry {
  value: unknown
  expiresAt: number
}

const cache = new Map<string, CacheEntry>()
const inFlight = new Map<string, Promise<unknown>>()

const DEFAULT_TTL_MS = 5_000

export function fetchCached<T>(
  key: string,
  fn: () => Promise<T>,
  opts?: { ttlMs?: number },
): Promise<T> {
  const ttlMs = opts?.ttlMs ?? DEFAULT_TTL_MS
  const hit = cache.get(key)
  if (hit && hit.expiresAt > Date.now()) return Promise.resolve(hit.value as T)
  const pending = inFlight.get(key)
  if (pending) return pending as Promise<T>
  const p = fn().then(
    (value) => {
      cache.set(key, { value, expiresAt: Date.now() + ttlMs })
      inFlight.delete(key)
      return value
    },
    (err: unknown) => {
      // Errors are never cached — the next caller retries the endpoint.
      inFlight.delete(key)
      throw err
    },
  )
  inFlight.set(key, p)
  return p
}

// Drop every cached entry whose key starts with `prefix`. Mutations call this so
// the next read after a write is always fresh (e.g. creating an agent invalidates
// 'agents'). In-flight promises are left alone: they were started before the
// mutation completed and their callers already hold the promise.
export function invalidateCached(prefix: string): void {
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) cache.delete(key)
  }
}

// Test hook — vitest resets module state between files but not between tests.
export function clearApiCache(): void {
  cache.clear()
  inFlight.clear()
}
