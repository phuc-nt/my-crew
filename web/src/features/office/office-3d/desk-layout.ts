// Pure layout: places N agent desks in a simple ring around the coordinator's center desk. No
// fixed per-agent-id positions (v1 decision from the phase's unresolved-questions section) — the
// grid grows/shrinks with however many distinct agents have appeared in the event stream so far.
const RING_RADIUS = 4

// v32 camera-fit: up to 8 desks keep the classic radius (positions byte-identical to
// v12-v31 — existing layout tests hold); bigger fleets widen the ring so desks never
// overlap, and the canvas camera pulls back from the same number (see office-canvas).
export function ringRadius(total: number): number {
  return total <= 8 ? RING_RADIUS : RING_RADIUS + (total - 8) * 0.45
}

export function deskPosition(index: number, total: number): [number, number, number] {
  const radius = ringRadius(total)
  if (total <= 0) return [0, 0, radius]
  const angle = (index / total) * Math.PI * 2
  const x = Math.sin(angle) * radius
  const z = Math.cos(angle) * radius
  return [x, 0, z]
}

// Where an avatar stands during a consult (v14): a point on the line between the two
// desks, biased 40% from OWN desk toward the colleague's — each side computes its own
// point, so the pair stops short of each other (gap = 20% of the desk-to-desk distance)
// instead of overlapping at the exact chord midpoint. Pure math (no r3f) so it is
// unit-testable in plain vitest, like deskPosition above.
const CONSULT_APPROACH = 0.4

export function consultMeetPoint(
  own: [number, number, number],
  other: [number, number, number],
): [number, number, number] {
  return [
    own[0] + (other[0] - own[0]) * CONSULT_APPROACH,
    own[1] + (other[1] - own[1]) * CONSULT_APPROACH,
    own[2] + (other[2] - own[2]) * CONSULT_APPROACH,
  ]
}
