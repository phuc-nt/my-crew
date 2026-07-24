// v55 pure helpers for the workroom list: recurring-run grouping + status filter +
// title search. Kept component-free so the collapse/filter rules are unit-testable
// without a DOM (same pattern as agent-office-state.ts).
//
// Grouping key = the EXACT title: recurring watch tasks re-run with an identical title
// ("[watch:jira-scrum] Có thay đổi…"), so dozens of runs collapse into one "×N" row.
// Two genuinely different tasks that happen to share a title also group — acceptable
// (the expanded rows still list every run individually, each selectable).
import type { Workroom } from '../../types'

export interface WorkroomGroup {
  title: string
  // Members newest-first (input order — the API already sorts by updated_at desc).
  rooms: Workroom[]
  // Rollup mirrors the backend's task→room rollup: any kẹt beats any đang-chạy beats xong.
  status: Workroom['status']
  updated_at: string
}

export type WorkroomStatus = Workroom['status']

export function groupWorkrooms(rooms: Workroom[]): WorkroomGroup[] {
  const byTitle = new Map<string, WorkroomGroup>()
  for (const room of rooms) {
    const group = byTitle.get(room.title)
    if (group) {
      group.rooms.push(room)
      if (room.updated_at > group.updated_at) group.updated_at = room.updated_at
      if (room.status === 'ket') group.status = 'ket'
      else if (room.status === 'dang-chay' && group.status === 'xong') group.status = 'dang-chay'
    } else {
      byTitle.set(room.title, {
        title: room.title, rooms: [room], status: room.status, updated_at: room.updated_at,
      })
    }
  }
  // Input is newest-first, so first-seen order already ranks groups by their newest run.
  return [...byTitle.values()]
}

// Counts by ROOM (not group) — the filter chips show real room totals.
export function countByStatus(rooms: Workroom[]): Record<WorkroomStatus, number> {
  const counts: Record<WorkroomStatus, number> = { 'dang-chay': 0, ket: 0, xong: 0 }
  for (const room of rooms) counts[room.status] += 1
  return counts
}

// Visibility rules (CEO decisions, v55 brainstorm):
// - a non-empty search matches by title substring and IGNORES the status filter
//   (finding an old ✓ room must not require toggling ✓ on first);
// - otherwise a group shows when its rollup status is enabled;
// - the ACTIVE room's group is always visible (deep-links via ?room=<id> must never
//   land on a filtered-out selection).
export function filterWorkroomGroups(
  groups: WorkroomGroup[],
  statuses: ReadonlySet<WorkroomStatus>,
  search: string,
  activeRoom: string | null,
): WorkroomGroup[] {
  const q = search.trim().toLowerCase()
  return groups.filter((g) => {
    if (activeRoom && g.rooms.some((r) => r.room_id === activeRoom)) return true
    if (q) return g.title.toLowerCase().includes(q)
    return statuses.has(g.status)
  })
}
