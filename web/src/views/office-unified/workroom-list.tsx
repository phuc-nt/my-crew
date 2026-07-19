// v16 rooms list — the left rail of the workroom office. Fetches /api/office/workrooms
// once + refetches when the caller signals a NEW assignment/milestone seq (guarded by
// the parent — this component is dumb). "Toàn cảnh" (no room) and "＋ Việc mới" are
// pseudo-entries above the real rooms.
//
// v54 P3: a $ cost chip per room, lazy per the v50 desk-inspector pattern — fetched
// ONLY for the selected room (never a fan-out over the whole list on mount), cached in
// a Record keyed by room_id so re-selecting an already-fetched room costs no request.
// `room_id` IS the task_id for a standalone task (v16 workroom convention), the same id
// `getTeamTaskCost` already keys on elsewhere (desk-inspector.tsx).
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'
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
  const { t } = useLanguage()
  const [costByRoom, setCostByRoom] = useState<Record<string, number>>({})

  useEffect(() => {
    if (!activeRoom || activeRoom in costByRoom) return
    let stop = false
    api.getTeamTaskCost(activeRoom)
      .then((c) => { if (!stop) setCostByRoom((prev) => ({ ...prev, [activeRoom]: c.total_cost_usd })) })
      .catch(() => undefined) // no chip on failure — never blocks room selection
    return () => { stop = true }
  }, [activeRoom, costByRoom])

  return (
    <nav className="workroom-list" aria-label={t('workroomList.ariaLabel')}>
      <p className="office-zone-title">{t('workroomList.title')}</p>
      <Button
        variant="chip"
        className={activeRoom === null ? 'chip-active' : undefined}
        onClick={() => onSelect(null)}
      >
        {t('workroomList.overview')}
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
          {r.task_count > 1 && (
            <span className="workroom-count"> ({t('workroomList.taskCount', { n: r.task_count })})</span>
          )}
          {r.room_id in costByRoom && (
            <span className="workroom-cost">{formatCost(costByRoom[r.room_id])}</span>
          )}
        </Button>
      ))}
    </nav>
  )
}
