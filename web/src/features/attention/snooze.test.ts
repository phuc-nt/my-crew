import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AttentionItem } from './attention-items'
import {
  SNOOZE_DAY_MS,
  SNOOZE_HOUR_MS,
  SNOOZE_STORAGE_KEY,
  isSnoozed,
  nextSnoozeExpiry,
  readSnoozed,
  withSnooze,
  writeSnoozed,
} from './snooze'

const store = new Map<string, string>()
beforeEach(() => {
  store.clear()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size
    },
  })
})

const item: AttentionItem = {
  id: 'alert:hr:failing',
  fingerprint: 'lỗi 3 lần',
  severity: 'warning',
  title: 'hr: đang lỗi liên tục',
  to: '/team/hr',
}

const NOW = 1_800_000_000_000

describe('snooze map', () => {
  it('hides a row until the deadline, and earlier if its content changes', () => {
    const map = withSnooze({}, item, SNOOZE_HOUR_MS, NOW)
    expect(isSnoozed(item, map, NOW)).toBe(true)
    expect(isSnoozed(item, map, NOW + SNOOZE_HOUR_MS - 1)).toBe(true)
    expect(isSnoozed(item, map, NOW + SNOOZE_HOUR_MS)).toBe(false)
    expect(isSnoozed({ ...item, fingerprint: 'lỗi 5 lần' }, map, NOW)).toBe(false)
  })

  it('round-trips through localStorage and drops expired or malformed entries on read', () => {
    const map = withSnooze(withSnooze({}, item, SNOOZE_DAY_MS, NOW), { ...item, id: 'old' }, 10, NOW)
    writeSnoozed(map)
    store.set(
      SNOOZE_STORAGE_KEY,
      JSON.stringify({ ...JSON.parse(store.get(SNOOZE_STORAGE_KEY)!), junk: { until: 'x' } }),
    )
    const back = readSnoozed(NOW + 100)
    expect(Object.keys(back)).toEqual([item.id])
    expect(back[item.id].until).toBe(NOW + SNOOZE_DAY_MS)
  })

  it('survives a corrupt store and a missing one', () => {
    store.set(SNOOZE_STORAGE_KEY, '{not json')
    expect(readSnoozed(NOW)).toEqual({})
    store.delete(SNOOZE_STORAGE_KEY)
    expect(readSnoozed(NOW)).toEqual({})
  })

  it('reports the earliest future deadline for the wake-up timer', () => {
    expect(nextSnoozeExpiry({}, NOW)).toBeNull()
    const map = {
      a: { fingerprint: 'x', until: NOW + 5000 },
      b: { fingerprint: 'y', until: NOW + 1000 },
      c: { fingerprint: 'z', until: NOW - 1 },
    }
    expect(nextSnoozeExpiry(map, NOW)).toBe(NOW + 1000)
  })
})
