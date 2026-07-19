// Task composer for the unified office screen (v15): type a brief — optionally leading
// with "@<agent>" (PIC chỉ định) or "@all" — submit for a plan preview, then Confirm/
// Cancel inline. When the backend already auto-confirmed (company flag), renders the
// done-card without buttons. The @-mention dropdown is fed by /api/office/assign/staff.
//
// `filterStaffForMention` is exported for unit tests (jsdom can't exercise the whole
// composer against a live stream, but the mention matching is the logic that matters).
import { useRef, useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/ui/button'
import type { AssignPreviewPayload, RoomChatPayload } from '../../types'

export interface StaffOption {
  id: string
  domain: string
}

// Returns dropdown options while the caret sits in a leading "@…" token: "" (just "@")
// lists everyone (plus the pseudo-entry @all), a partial like "@no" narrows by prefix
// then substring. A brief not starting with "@" never shows the dropdown.
export function filterStaffForMention(brief: string, staff: StaffOption[]): StaffOption[] {
  const m = /^@([A-Za-z0-9_.-]*)$/.exec(brief.trimStart().split(/\s/, 1)[0] ?? '')
  if (!m || /\s/.test(brief.trimStart())) return [] // token complete once a space follows
  const q = m[1].toLowerCase()
  const all: StaffOption = { id: 'all', domain: 'đội tự chọn PIC' }
  const pool = [all, ...staff]
  if (!q) return pool
  const starts = pool.filter((s) => s.id.toLowerCase().startsWith(q))
  const contains = pool.filter(
    (s) => !s.id.toLowerCase().startsWith(q) && s.id.toLowerCase().includes(q),
  )
  return [...starts, ...contains]
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'previewing' }
  | { kind: 'preview'; data: AssignPreviewPayload }
  | { kind: 'adjust-preview'; data: RoomChatPayload }
  | { kind: 'reply'; text: string }
  | { kind: 'confirming' }
  | { kind: 'done'; text: string; auto: boolean }
  | { kind: 'error'; message: string }

interface AssignComposerProps {
  // v16: null = toàn cảnh (giao việc mới, room mới); set = chat-in-room (3 intent).
  activeRoom?: string | null
  // Called with the new task's id after a successful toàn-cảnh confirm — parent
  // switches into the task's brand-new room.
  onTaskCreated?: (taskId: string) => void
}

export function AssignComposer({ activeRoom = null, onTaskCreated }: AssignComposerProps) {
  const [brief, setBrief] = useState('')
  const [staff, setStaff] = useState<StaffOption[]>([])
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const fetchedStaff = useRef(false)

  // Roster fetched once on first focus — cheap, and the list only changes when the
  // CEO edits the fleet (a reload is fine then).
  const ensureStaff = () => {
    if (fetchedStaff.current) return
    fetchedStaff.current = true
    api.getAssignableStaff().then((p) => setStaff(p.staff)).catch(() => setStaff([]))
  }

  const mentions = filterStaffForMention(brief, staff)

  const applyMention = (id: string) => {
    setBrief(`@${id} `)
  }

  const submit = () => {
    // A live preview must be confirmed or cancelled first — resubmitting over it
    // would orphan the previewed draft row (review m5).
    if (phase.kind === 'preview' || phase.kind === 'adjust-preview') return
    if (!brief.trim() || phase.kind === 'previewing' || phase.kind === 'confirming') return
    setPhase({ kind: 'previewing' })
    if (activeRoom) {
      // v16 chat-in-room: backend routes the message to question/adjust/new_task.
      api
        .roomChat(activeRoom, brief.trim())
        .then((data) => {
          if (data.intent === 'question') {
            setPhase({ kind: 'reply', text: data.reply ?? '' })
            setBrief('')
          } else if (data.intent === 'adjust') {
            if (data.amendment_id) setPhase({ kind: 'adjust-preview', data })
            else { setPhase({ kind: 'reply', text: data.reply ?? '' }); setBrief('') }
          } else if (data.auto_confirmed) {
            setPhase({ kind: 'done', text: data.preview_text ?? '', auto: true })
            setBrief('')
          } else {
            setPhase({ kind: 'preview', data: {
              preview_text: data.preview_text ?? '', task_id: data.task_id ?? '',
              plan_hash: data.plan_hash ?? '', pic_id: data.pic_id ?? '',
              auto_confirmed: false,
            } })
          }
        })
        .catch((e: unknown) =>
          setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'gửi thất bại' }),
        )
      return
    }
    api
      .assignPreview(brief.trim())
      .then((data) => {
        if (data.auto_confirmed) {
          setPhase({ kind: 'done', text: data.preview_text, auto: true })
          setBrief('')
          if (data.task_id) onTaskCreated?.(data.task_id)
        } else {
          setPhase({ kind: 'preview', data })
        }
      })
      .catch((e: unknown) =>
        setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'giao việc thất bại' }),
      )
  }

  const confirmAdjust = (data: RoomChatPayload) => {
    if (phase.kind !== 'adjust-preview' || !activeRoom) return
    setPhase({ kind: 'confirming' })
    api
      .roomConfirmAdjust(activeRoom, data.task_id ?? '', data.amendment_id ?? '')
      .then((r) => { setPhase({ kind: 'done', text: r.text, auto: false }); setBrief('') })
      .catch((e: unknown) =>
        setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'xác nhận sửa thất bại' }),
      )
  }

  const confirm = (data: AssignPreviewPayload) => {
    if (phase.kind !== 'preview') return // double-click guard (review m6)
    setPhase({ kind: 'confirming' })
    api
      .assignConfirm(data.task_id, data.plan_hash)
      .then((r) => {
        setPhase({ kind: 'done', text: r.text, auto: false })
        setBrief('')
        if (!activeRoom && data.task_id) onTaskCreated?.(data.task_id)
      })
      .catch((e: unknown) =>
        setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'xác nhận thất bại' }),
      )
  }

  const cancel = (data: AssignPreviewPayload) => {
    api.assignCancel(data.task_id).catch(() => undefined) // draft cleanup is best-effort
    setPhase({ kind: 'idle' })
  }

  return (
    <div className="office-composer">
      <div className="office-composer-row">
        <input
          type="text"
          value={brief}
          placeholder={activeRoom
            ? 'Chat trong phòng việc… (hỏi tiến độ / "chỉnh: …" / "giao …" việc mới)'
            : 'Giao việc… (@tên-nhân-sự để chỉ định PIC, @all hoặc bỏ trống để đội tự chọn)'}
          onFocus={ensureStaff}
          onChange={(e) => {
            setBrief(e.target.value)
            if (phase.kind === 'error' || phase.kind === 'done') setPhase({ kind: 'idle' })
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
        />
        <Button variant="ghost" onClick={submit} disabled={phase.kind === 'previewing'}>
          {phase.kind === 'previewing' ? 'Đang xử lý…' : activeRoom ? 'Gửi' : 'Giao việc'}
        </Button>
      </div>
      {mentions.length > 0 && (
        <ul className="office-composer-mentions" role="listbox">
          {/* v53: styled by container element selector (.office-composer-mentions button) — unify in a later pass */}
          {mentions.map((s) => (
            <li key={s.id}>
              <button type="button" onClick={() => applyMention(s.id)}>
                @{s.id} <span className="office-composer-domain">({s.domain})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {phase.kind === 'preview' && (
        <div className="office-composer-preview">
          <pre>{phase.data.preview_text}</pre>
          <div className="office-composer-actions">
            <Button variant="primary" onClick={() => confirm(phase.data)}>
              Xác nhận giao việc
            </Button>
            <Button variant="ghost" onClick={() => cancel(phase.data)}>
              Huỷ
            </Button>
          </div>
        </div>
      )}
      {phase.kind === 'reply' && (
        <div className="office-composer-preview office-composer-reply">
          <pre>{phase.text}</pre>
        </div>
      )}
      {phase.kind === 'adjust-preview' && (
        <div className="office-composer-preview">
          <pre>{phase.data.preview_text}</pre>
          <div className="office-composer-actions">
            <Button variant="primary" onClick={() => confirmAdjust(phase.data)}>
              Xác nhận sửa kế hoạch
            </Button>
            <Button variant="ghost" onClick={() => setPhase({ kind: 'idle' })}>Bỏ qua</Button>
          </div>
        </div>
      )}
      {phase.kind === 'confirming' && <p className="office-room-status">Đang xác nhận…</p>}
      {phase.kind === 'done' && (
        <div className="office-composer-preview office-composer-done">
          <pre>{phase.text}</pre>
          {phase.auto && <p className="office-room-status">Đã tự xác nhận (chế độ tự xác nhận đang bật).</p>}
        </div>
      )}
      {phase.kind === 'error' && <p className="error">Lỗi: {phase.message}</p>}
    </div>
  )
}
