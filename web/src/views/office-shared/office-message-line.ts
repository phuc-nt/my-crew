// Shared office-event → one-line Vietnamese text rendering (v15): extracted from
// OfficeRoom.tsx so the unified office screen's activity feed and the timeline tab
// render an event IDENTICALLY (one vocabulary, one place to extend). Pure functions —
// no hooks, no r3f — unit-testable in plain vitest. PHASE_LABEL is re-used from the 3D
// bubble (same closed-set backend vocabulary, one source of truth).
import type { OfficeEventKind, OfficeMessage } from '../../types'
import { PHASE_LABEL } from '../office-3d/speech-bubble'

export const KIND_LABEL: Record<OfficeEventKind, string> = {
  ceo: 'CEO giao việc',
  assignment: 'Phân công',
  step_status: 'Tiến độ bước',
  handoff: 'Bàn giao',
  milestone: 'Cột mốc',
  consult: 'Tham vấn',
  review: 'Soát chéo',
}

export function messageLine(m: OfficeMessage): string {
  const b = m.body
  switch (m.kind) {
    case 'ceo':
      return b.text ?? ''
    case 'assignment': {
      // v15: `pic` names the staffer responsible for the whole task. The backend's
      // `summary` may already lead with "PIC: x" — only prefix here when it doesn't
      // (older events / other writers), so the line never reads "PIC: x — PIC: x — …".
      const base = `${b.task_title ?? ''} — ${b.summary ?? ''} (${b.step_count ?? 0} bước)`
      const pic = b.pic ?? ''
      return pic && !(b.summary ?? '').includes(`PIC: ${pic}`)
        ? `${base} — PIC: ${pic}`
        : base
    }
    case 'step_status': {
      const phaseLabel = b.phase ? PHASE_LABEL[b.phase] : undefined
      const suffix = phaseLabel ? ` (${phaseLabel})` : ''
      // v34 P2: the one non-self-explanatory status value gets a human label — the
      // rest (started/done/failed) read fine as-is and stay byte-identical.
      const status = b.status === 'waiting_clarify' ? 'chờ CEO trả lời' : (b.status ?? '')
      return `${b.task_title ?? ''} / ${b.step_title ?? ''}: ${status}${suffix}`
    }
    case 'handoff':
      // v17: the feed is an index, not a report viewer — the FULL result lives in the
      // Kết quả column (artifact viewer), so the line stays a fixed short notice.
      return `${b.task_title ?? ''} / ${b.step_title ?? ''}: đã bàn giao ✅ (xem cột Kết quả)`
    case 'milestone':
      return `${b.task_title ?? ''}: ${b.message ?? ''}`
    case 'consult':
      return `${b.from ?? ''} hỏi ${b.to ?? ''}: ${b.question_summary ?? ''} → ${b.answer_summary ?? ''}`
    case 'review': {
      const verdictLabel = b.verdict === 'passed' ? 'đạt' : `cần sửa (${b.failure_count ?? 0} lỗi)`
      // v34 P5: per-criterion count when the verdict graded a checklist (0 = pre-P5
      // event or no criteria on the step — omit rather than show "0/0").
      const checklist = b.criteria_total ? ` — ${b.criteria_passed ?? 0}/${b.criteria_total} tiêu chí đạt` : ''
      return `${b.task_title ?? ''} / ${b.step_title ?? ''}: ${verdictLabel}${checklist}`
    }
    default:
      return ''
  }
}
