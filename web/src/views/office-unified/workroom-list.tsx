// v16 rooms list — right column of the workroom office. Fetches /api/office/workrooms
// once + refetches when the caller signals a NEW assignment/milestone seq (guarded by
// the parent — this component is dumb).
//
// v55 cockpit: the flat, ever-growing list (each watch run = a new room) becomes
// status-filter chips [●|⚠|✓] (✓ off by default — finished rooms are history, not
// work), a title search (which ignores the status filter — see workroom-grouping.ts),
// and recurring runs collapsed into one "×N" row. Pure rules live in
// workroom-grouping.ts; this component only renders.
//
// v54 P3: a $ cost chip per room, lazy per the v50 desk-inspector pattern — fetched
// ONLY for the selected room (never a fan-out over the whole list on mount), cached in
// a Record keyed by room_id so re-selecting an already-fetched room costs no request.
// `room_id` IS the task_id for a standalone task (v16 workroom convention), the same id
// `getTeamTaskCost` already keys on elsewhere (desk-inspector.tsx).
import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { useLanguage } from '../../i18n/language-context'
import { formatCost, formatDateTime } from '../../labels'
import type { Workroom } from '../../types'
import {
  countByStatus, filterWorkroomGroups, groupWorkrooms,
  type WorkroomGroup, type WorkroomStatus,
} from './workroom-grouping'

const STATUS_BADGE: Record<Workroom['status'], string> = {
  'dang-chay': '●', ket: '⚠', xong: '✓',
}
// ✓ starts OFF: at rest a fleet has dozens of finished watch runs — they are history,
// the default view is "what needs eyes" (đang chạy + kẹt).
const DEFAULT_STATUSES: ReadonlySet<WorkroomStatus> = new Set(['dang-chay', 'ket'])

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
  const [statuses, setStatuses] = useState<ReadonlySet<WorkroomStatus>>(DEFAULT_STATUSES)
  const [search, setSearch] = useState('')
  const [expandedTitles, setExpandedTitles] = useState<ReadonlySet<string>>(new Set())

  useEffect(() => {
    if (!activeRoom || activeRoom in costByRoom) return
    let stop = false
    api.getTeamTaskCost(activeRoom)
      .then((c) => { if (!stop) setCostByRoom((prev) => ({ ...prev, [activeRoom]: c.total_cost_usd })) })
      .catch(() => undefined) // no chip on failure — never blocks room selection
    return () => { stop = true }
  }, [activeRoom, costByRoom])

  const groups = useMemo(() => groupWorkrooms(rooms), [rooms])
  const counts = useMemo(() => countByStatus(rooms), [rooms])
  const visible = useMemo(
    () => filterWorkroomGroups(groups, statuses, search, activeRoom),
    [groups, statuses, search, activeRoom],
  )
  const hiddenCount = groups.length - visible.length

  const toggleStatus = (s: WorkroomStatus) => {
    setStatuses((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }
  const toggleExpanded = (title: string) => {
    setExpandedTitles((prev) => {
      const next = new Set(prev)
      if (next.has(title)) next.delete(title)
      else next.add(title)
      return next
    })
  }

  const roomChip = (r: Workroom, label: string) => (
    <Button
      key={r.room_id}
      variant="chip"
      className={activeRoom === r.room_id ? 'chip-active workroom-item' : 'workroom-item'}
      onClick={() => onSelect(r.room_id)}
      title={r.title}
    >
      <span className={`workroom-status workroom-${r.status}`}>{STATUS_BADGE[r.status]}</span>{' '}
      {needsShellRooms?.has(r.room_id) ? '🔒 ' : ''}
      {label}
      {r.task_count > 1 ? (
        <span className="workroom-count"> ({t('workroomList.taskCount', { n: r.task_count })})</span>
      ) : null}
      {r.room_id in costByRoom ? (
        <span className="workroom-cost">{formatCost(costByRoom[r.room_id])}</span>
      ) : null}
    </Button>
  )

  const groupRow = (g: WorkroomGroup) => {
    // The active room's group must be browsable even if never manually expanded —
    // a deep-link (?room=<id>) into a collapsed run auto-opens its group.
    const expanded = expandedTitles.has(g.title)
      || (activeRoom !== null && g.rooms.some((r) => r.room_id === activeRoom))
    const shortTitle = g.title.length > 34 ? `${g.title.slice(0, 33)}…` : g.title
    return (
      <div key={g.title}>
        <Button
          variant="chip"
          className="workroom-item"
          onClick={() => toggleExpanded(g.title)}
          title={g.title}
          aria-expanded={expanded}
        >
          {expanded ? '▾' : '▸'}{' '}
          <span className={`workroom-status workroom-${g.status}`}>{STATUS_BADGE[g.status]}</span>{' '}
          {shortTitle}
          <span className="workroom-count"> ×{g.rooms.length}</span>
        </Button>
        {expanded ? (
          <div className="workroom-group-runs">
            {/* Runs share one title — label each by its time (fallback: title, never blank). */}
            {g.rooms.map((r) => roomChip(r, formatDateTime(r.updated_at) || shortTitle))}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <nav className="workroom-list" aria-label={t('workroomList.ariaLabel')}>
      <Button
        variant="chip"
        className={activeRoom === null ? 'chip-active' : undefined}
        onClick={() => onSelect(null)}
      >
        {t('workroomList.overview')}
      </Button>
      <div className="workroom-filters">
        {(['dang-chay', 'ket', 'xong'] as const).map((s) => (
          <Button
            key={s}
            variant="chip"
            className={statuses.has(s) ? 'chip-active' : undefined}
            onClick={() => toggleStatus(s)}
            title={t(`workroomList.filter.${s}`)}
          >
            <span className={statuses.has(s) ? undefined : `workroom-${s}`}>{STATUS_BADGE[s]}</span>
            {' '}{counts[s]}
          </Button>
        ))}
      </div>
      <Input
        className="workroom-search"
        value={search}
        placeholder={t('workroomList.searchPlaceholder')}
        onChange={(e) => setSearch(e.target.value)}
      />
      {visible.map((g) => (g.rooms.length === 1
        ? roomChip(g.rooms[0], g.title.length > 34 ? `${g.title.slice(0, 33)}…` : g.title)
        : groupRow(g)))}
      {visible.length === 0 ? (
        <EmptyState>{t('workroomList.emptyFiltered')}</EmptyState>
      ) : null}
      {hiddenCount > 0 && !search ? (
        <p className="workroom-hidden-hint">{t('workroomList.hiddenHint', { n: hiddenCount })}</p>
      ) : null}
    </nav>
  )
}
