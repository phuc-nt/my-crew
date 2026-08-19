// Pure-math coverage for the v14 consult walk target (consultMeetPoint) + the ring
// layout it composes with. Canvas/useFrame is not testable in jsdom (see
// office-unified.test.tsx's header) — the tween TARGET is the testable seam.
import { expect, test } from 'vitest'
import { consultMeetPoint, deskPosition, ringRadius } from './desk-layout'

test('consultMeetPoint sits 40% of the way from own desk toward the colleague', () => {
  expect(consultMeetPoint([0, 0, 0], [10, 0, 0])).toEqual([4, 0, 0])
  expect(consultMeetPoint([2, 0, -4], [2, 0, 6])).toEqual([2, 0, 0])
})

test('the two consult parties end up close but NOT on the same spot (facing each other)', () => {
  const a: [number, number, number] = deskPosition(0, 4)
  const b: [number, number, number] = deskPosition(2, 4)
  const pa = consultMeetPoint(a, b)
  const pb = consultMeetPoint(b, a)
  const gap = Math.hypot(pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2])
  const full = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
  expect(gap).toBeGreaterThan(0.5) // not overlapping
  expect(gap).toBeLessThan(full * 0.3) // but genuinely "walked toward each other"
})

test('consulting yourself (degenerate same-position input) stays at own desk, no NaN', () => {
  const p = consultMeetPoint([1, 0, 2], [1, 0, 2])
  expect(p).toEqual([1, 0, 2])
})

// v32 camera-fit: small fleets keep the classic ring (positions stable — the
// assertions above must hold unchanged); bigger fleets widen so desks don't overlap.
test('ringRadius keeps the classic radius up to 8 desks, then widens', () => {
  expect(ringRadius(3)).toBe(4)
  expect(ringRadius(8)).toBe(4)
  expect(ringRadius(12)).toBeGreaterThan(4)
})
