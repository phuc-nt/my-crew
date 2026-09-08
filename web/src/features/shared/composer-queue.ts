// v94: queued follow-ups for the composer. While a preview/confirm round-trip is in
// flight the CEO can keep typing; each Enter parks the text here and the composer
// flushes one entry as soon as it is free again. Pure rules, so the "when" is unit-
// testable without rendering the composer.

/** Phases during which a new submit must wait rather than run. */
const BUSY = new Set(['previewing', 'confirming'])
/** Phases in which the composer may pick the next queued entry on its own. A live
 *  preview is NOT one of them — the CEO must confirm or cancel it first, and 'error'
 *  is excluded so a failing backend cannot drain the queue into repeated failures. */
const FLUSHABLE = new Set(['idle', 'reply', 'done'])

export function shouldQueue(phaseKind: string): boolean {
  return BUSY.has(phaseKind)
}

export function canFlush(phaseKind: string, queued: readonly string[]): boolean {
  return queued.length > 0 && FLUSHABLE.has(phaseKind)
}

/** Append, ignoring blank text; returns the same array when nothing was added. */
export function enqueue(queued: readonly string[], text: string): readonly string[] {
  const trimmed = text.trim()
  return trimmed ? [...queued, trimmed] : queued
}
