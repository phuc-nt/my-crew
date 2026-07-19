// v16 rooms list — the left rail of the workroom office. Fetches /api/office/workrooms
// once + refetches when the caller signals a NEW assignment/milestone seq (guarded by
// the parent — this component is dumb). "Toàn cảnh" (no room) and "＋ Việc mới" are
// pseudo-entries above the real rooms.
import { Button } from '../../components/ui/button'
import type { Workroom } from '../../types'

const STATUS_BADGE: Record<Workroom['status'], string> = {
  'dang-chay': '●', ket: '⚠', xong: '✓',
}

interface WorkroomListProps {
  rooms: Workroom[]
  activeRoom: string | null // null = toàn cảnh
  onSelect: (roomId: string | null) => void
  // Dual-lens P1 (high-mode only — parent passes an empty set in low mode): rooms whose
  // task has sandbox (needs_shell) steps, joined by room_id from the board API.
  needsShellRooms?: Set<string>
}

export function WorkroomList({ rooms, activeRoom, onSelect, needsShellRooms }: WorkroomListProps) {
  return (
    <nav className="workroom-list" aria-label="Phòng việc">
      <p className="office-zone-title">Phòng việc</p>
      <Button
        variant="chip"
        className={activeRoom === null ? 'chip-active' : undefined}
        onClick={() => onSelect(null)}
      >
        Toàn cảnh
      </Button>
      {rooms.map((r) => (
        <Button
          key={r.room_id}
          variant="chip"
          className={activeRoom === r.room_id ? 'chip-active workroom-item' : 'workroom-item'}
          onClick={() => onSelect(r.room_id)}
          title={r.title}
        >
          <span className={`workroom-status workroom-${r.status}`}>{STATUS_BADGE[r.status]}</span>{' '}
          {needsShellRooms?.has(r.room_id) ? '🔒 ' : ''}
          {r.title.length > 34 ? `${r.title.slice(0, 33)}…` : r.title}
          {r.task_count > 1 && <span className="workroom-count"> ({r.task_count} việc)</span>}
        </Button>
      ))}
    </nav>
  )
}
