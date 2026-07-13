// "Kết quả" column (v17): delivered-step catalog for the selected workroom, grouped by
// task. Only steps that actually HAVE a handoff artifact are listed — done work/rework
// steps (a review-step's verdict lives in a different file and would always 404,
// red-team M1). Click opens the full-markdown ArtifactViewer.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { OfficeMessage, RoomArtifactsPayload } from '../../types'
import { ArtifactViewer } from './artifact-viewer'

// Pure refetch signal (red-team m-refetch): highest seq among the given kinds — the
// caller refetches when this grows. NOT shared state with workroom-list's own signal.
export function maxSeqOf(messages: OfficeMessage[], kinds: string[]): number {
  return messages
    .filter((m) => kinds.includes(m.kind))
    .reduce((mx, m) => Math.max(mx, m.seq), 0)
}

interface ArtifactPanelProps {
  activeRoom: string | null
  roomMessages: OfficeMessage[]
}

export function ArtifactPanel({ activeRoom, roomMessages }: ArtifactPanelProps) {
  const [data, setData] = useState<RoomArtifactsPayload | null>(null)
  const [open, setOpen] = useState<{ taskId: string; seq: number; stepId: string } | null>(null)

  // Refetch when the room changes OR a new handoff/review lands in THIS room's stream.
  const signal = maxSeqOf(roomMessages, ['handoff', 'review'])
  useEffect(() => {
    if (!activeRoom) { setData(null); return }
    api.getRoomArtifacts(activeRoom).then(setData).catch(() => setData(null))
  }, [activeRoom, signal])

  if (!activeRoom) {
    return (
      <aside className="office-artifacts" aria-label="Kết quả">
        <p className="office-zone-title">Kết quả</p>
        <p className="ops-chat-empty">Chọn một phòng việc để xem kết quả bàn giao.</p>
      </aside>
    )
  }

  const tasks = (data?.tasks ?? []).map((t) => ({
    ...t,
    delivered: t.steps.filter(
      (s) => s.status === 'done' && (s.step_type === 'work' || s.step_type === 'rework'),
    ),
  }))
  const hasAny = tasks.some((t) => t.delivered.length > 0)

  return (
    <aside className="office-artifacts" aria-label="Kết quả">
      <p className="office-zone-title">Kết quả</p>
      {!hasAny && <p className="ops-chat-empty">Chưa có bàn giao nào trong phòng này.</p>}
      {tasks.map((t) => t.delivered.length > 0 && (
        <section key={t.task_id} className="artifact-task">
          <h4 title={t.title}>
            {t.title.length > 40 ? `${t.title.slice(0, 39)}…` : t.title}
            {t.pic_id && <span className="office-3d-bubble-pic artifact-pic">PIC: {t.pic_id}</span>}
          </h4>
          <ul>
            {t.delivered.map((s) => (
              <li key={s.step_id}>
                <button
                  type="button"
                  className="artifact-item"
                  onClick={() => setOpen({ taskId: t.task_id, seq: s.seq, stepId: s.step_id })}
                >
                  ✅ {s.title} <span className="office-composer-domain">({s.assigned_to})</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {open && (
        <ArtifactViewer
          taskId={open.taskId} seq={open.seq} stepId={open.stepId}
          onClose={() => setOpen(null)}
        />
      )}
    </aside>
  )
}
