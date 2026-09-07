// Shared bits for the Số liệu panels: the day-window choices and the tone rules, so
// every panel colours "how full" the same way.
export type LevelTone = 'ok' | 'warn' | 'danger'

export const DAY_CHOICES = [1, 7, 30, 90] as const
export const DEFAULT_DAYS = 7

/** Parse `?days=` — anything outside the choices falls back to the default. */
export function parseDays(raw: string | null): number {
  const n = Number(raw)
  return (DAY_CHOICES as readonly number[]).includes(n) ? n : DEFAULT_DAYS
}

/** Budget tone: green until 80 %, amber until the cap, red at or over it. */
export function ratioTone(ratio: number): LevelTone {
  if (ratio >= 1) return 'danger'
  if (ratio >= 0.8) return 'warn'
  return 'ok'
}

/** Failure-rate tone: a tenth failing is a warning, a quarter is a problem. */
export function failureTone(rate: number): LevelTone {
  if (rate >= 0.25) return 'danger'
  if (rate >= 0.1) return 'warn'
  return 'ok'
}

export function pct(ratio: number): string {
  return `${(ratio * 100).toFixed(0)}%`
}
