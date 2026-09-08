// The queue's "when": park while a round-trip is in flight, flush only once the
// composer is genuinely free — never over a live preview, never after an error.
import { describe, expect, it } from 'vitest'
import { canFlush, enqueue, shouldQueue } from './composer-queue'

describe('composer queue rules', () => {
  it('queues only while a preview or confirm is in flight', () => {
    expect(shouldQueue('previewing')).toBe(true)
    expect(shouldQueue('confirming')).toBe(true)
    for (const k of ['idle', 'preview', 'adjust-preview', 'reply', 'done', 'error'])
      expect(shouldQueue(k)).toBe(false)
  })

  it('flushes in idle/reply/done, never over a live preview or after an error', () => {
    const q = ['tiếp theo']
    expect(canFlush('idle', q)).toBe(true)
    expect(canFlush('reply', q)).toBe(true)
    expect(canFlush('done', q)).toBe(true)
    expect(canFlush('preview', q)).toBe(false)
    expect(canFlush('adjust-preview', q)).toBe(false)
    expect(canFlush('error', q)).toBe(false)
    expect(canFlush('previewing', q)).toBe(false)
    expect(canFlush('idle', [])).toBe(false)
  })

  it('trims and drops blank entries without touching the array', () => {
    const q: readonly string[] = ['a']
    expect(enqueue(q, '   ')).toBe(q)
    expect(enqueue(q, '  b  ')).toEqual(['a', 'b'])
  })
})
