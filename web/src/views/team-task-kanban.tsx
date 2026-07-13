// v33 P3: read-only kanban over team tasks — lanes mirror the store statuses
// (planning drafts included so the CEO sees what still awaits confirm). A card links
// to its workroom; moving cards stays with the existing chat-command/gateway path,
// deliberately NOT a drag-drop write surface.
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import type { TeamBoardLane } from '../types'

const LANE_LABEL: Record<string, string> = {
  planning: 'Chờ xác nhận',
  open: 'Sẵn sàng',
  running: 'Đang chạy',
  done: 'Xong',
  khac: 'Kẹt',
}

export function TeamTaskKanban() {
  const [lanes, setLanes] = useState<TeamBoardLane[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getTeamTaskBoard()
      .then((res) => setLanes(res.lanes))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : 'không tải được bảng việc đội'),
      )
  }, [])

  const total = lanes.reduce((n, l) => n + l.cards.length, 0)
  if (error) return <p className="error">{error}</p>
  if (total === 0) return null

  return (
    <section className="team-kanban">
      <h3>Việc của đội</h3>
      <div className="team-kanban-lanes">
        {lanes.map(
          (lane) =>
            lane.cards.length > 0 && (
              <div key={lane.id} className="team-kanban-lane">
                <p className="office-zone-title">
                  {LANE_LABEL[lane.id] ?? lane.id} ({lane.cards.length})
                </p>
                {lane.cards.map((c) => (
                  <Link
                    key={c.task_id}
                    className="team-kanban-card"
                    to={`/office?room=${encodeURIComponent(c.room_id)}`}
                  >
                    <span className="team-kanban-title">{c.title}</span>
                    <span className="team-kanban-meta">
                      {c.pic_id && <span className="outputs-agent">@{c.pic_id}</span>}
                      {c.steps_total > 0 && (
                        <span className="muted">
                          {c.steps_done}/{c.steps_total} bước
                        </span>
                      )}
                    </span>
                  </Link>
                ))}
              </div>
            ),
        )}
      </div>
    </section>
  )
}
