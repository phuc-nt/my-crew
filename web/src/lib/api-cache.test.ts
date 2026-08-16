import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearApiCache, fetchCached, invalidateCached } from './api-cache'

beforeEach(() => {
  clearApiCache()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

test('a TTL hit returns the cached value without calling the fetcher again', async () => {
  const fn = vi.fn().mockResolvedValue('v1')
  expect(await fetchCached('k', fn)).toBe('v1')
  expect(await fetchCached('k', fn)).toBe('v1')
  expect(fn).toHaveBeenCalledTimes(1)
})

test('after the TTL expires the fetcher runs again', async () => {
  const fn = vi.fn().mockResolvedValueOnce('v1').mockResolvedValueOnce('v2')
  expect(await fetchCached('k', fn, { ttlMs: 1_000 })).toBe('v1')
  vi.advanceTimersByTime(1_001)
  expect(await fetchCached('k', fn, { ttlMs: 1_000 })).toBe('v2')
  expect(fn).toHaveBeenCalledTimes(2)
})

test('concurrent callers share one in-flight promise', async () => {
  let resolve!: (v: string) => void
  const fn = vi.fn().mockReturnValue(new Promise<string>((r) => (resolve = r)))
  const a = fetchCached('k', fn)
  const b = fetchCached('k', fn)
  resolve('shared')
  expect(await a).toBe('shared')
  expect(await b).toBe('shared')
  expect(fn).toHaveBeenCalledTimes(1)
})

test('a rejected fetch is never cached — the next caller retries', async () => {
  const fn = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce('ok')
  await expect(fetchCached('k', fn)).rejects.toThrow('boom')
  expect(await fetchCached('k', fn)).toBe('ok')
  expect(fn).toHaveBeenCalledTimes(2)
})

test('invalidateCached drops entries by prefix, leaving others cached', async () => {
  const agents = vi.fn().mockResolvedValue('a')
  const health = vi.fn().mockResolvedValue('h')
  await fetchCached('agents', agents)
  await fetchCached('coordinator-health', health)

  invalidateCached('agents')

  await fetchCached('agents', agents) // refetches — invalidated
  await fetchCached('coordinator-health', health) // still cached
  expect(agents).toHaveBeenCalledTimes(2)
  expect(health).toHaveBeenCalledTimes(1)
})

test('distinct keys never share a cache entry', async () => {
  const fn1 = vi.fn().mockResolvedValue(1)
  const fn2 = vi.fn().mockResolvedValue(2)
  expect(await fetchCached('one', fn1)).toBe(1)
  expect(await fetchCached('two', fn2)).toBe(2)
  expect(fn1).toHaveBeenCalledTimes(1)
  expect(fn2).toHaveBeenCalledTimes(1)
})
