// v96: "nhắc lại sau" for an attention row. A dismissal hides a row until its substance
// changes; a snooze hides it until a clock runs out — the right tool when the CEO knows
// about the thing and wants it back in an hour, not gone. Same shape as the dismissal
// map (id → fingerprint) plus the deadline, so a row whose content changed mid-snooze
// still comes back early.
import type { AttentionItem } from './attention-items'

export const SNOOZE_STORAGE_KEY = 'my-crew.attention.snoozed'

export const SNOOZE_HOUR_MS = 60 * 60 * 1000
export const SNOOZE_DAY_MS = 24 * SNOOZE_HOUR_MS

export interface SnoozeEntry {
  fingerprint: string
  /** Epoch ms after which the row shows again. */
  until: number
}

export type SnoozedMap = Record<string, SnoozeEntry>

function isEntry(v: unknown): v is SnoozeEntry {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as SnoozeEntry).fingerprint === 'string' &&
    typeof (v as SnoozeEntry).until === 'number' &&
    Number.isFinite((v as SnoozeEntry).until)
  )
}

/** Expired and malformed entries are dropped on read, so the map never outlives its rows. */
export function readSnoozed(now: number = Date.now()): SnoozedMap {
  try {
    const raw = localStorage.getItem(SNOOZE_STORAGE_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return {}
    const out: SnoozedMap = {}
    for (const [id, entry] of Object.entries(parsed as Record<string, unknown>)) {
      if (isEntry(entry) && entry.until > now) out[id] = entry
    }
    return out
  } catch {
    return {}
  }
}

export function writeSnoozed(map: SnoozedMap): void {
  try {
    localStorage.setItem(SNOOZE_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // Private mode / quota: the snooze still holds for this page load.
  }
}

export function isSnoozed(item: AttentionItem, map: SnoozedMap, now: number): boolean {
  const entry = map[item.id]
  return entry != null && entry.fingerprint === item.fingerprint && entry.until > now
}

export function withSnooze(
  map: SnoozedMap,
  item: AttentionItem,
  durationMs: number,
  now: number = Date.now(),
): SnoozedMap {
  return { ...map, [item.id]: { fingerprint: item.fingerprint, until: now + durationMs } }
}

/** The earliest future deadline, so the hook can wake exactly when a row is due back. */
export function nextSnoozeExpiry(map: SnoozedMap, now: number): number | null {
  let next: number | null = null
  for (const entry of Object.values(map)) {
    if (entry.until > now && (next === null || entry.until < next)) next = entry.until
  }
  return next
}
