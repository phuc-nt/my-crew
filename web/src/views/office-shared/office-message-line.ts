// Shared office-event → one-line text rendering (v15): extracted from OfficeRoom.tsx so
// the unified office screen's activity feed and the timeline tab render an event
// IDENTICALLY (one vocabulary, one place to extend). Pure functions — no hooks, no r3f —
// unit-testable in plain vitest. PHASE_LABEL is re-used from the 3D bubble (same
// closed-set backend vocabulary, one source of truth).
//
// v53 i18n: both kindLabel and messageLine take an optional `t` (useLanguage()'s
// translate fn), defaulting to DICT.vi (same fallback pattern as agent-desk.tsx) for any
// caller without language-context access.
import { DICT } from '../../i18n/dictionary'
import type { UiKey } from '../../i18n/dictionary'
import type { OfficeEventKind, OfficeMessage } from '../../types'
import { PHASE_LABEL } from '../office-3d/speech-bubble'

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

const defaultT: Translate = (key, params) => {
  let s: string = DICT.vi[key]
  if (params) for (const [k, v] of Object.entries(params)) s = s.replaceAll(`{${k}}`, String(v))
  return s
}

const KIND_LABEL_KEY: Record<OfficeEventKind, UiKey> = {
  ceo: 'officeMessageLine.kindCeo',
  assignment: 'officeMessageLine.kindAssignment',
  step_status: 'officeMessageLine.kindStepStatus',
  handoff: 'officeMessageLine.kindHandoff',
  milestone: 'officeMessageLine.kindMilestone',
  consult: 'officeMessageLine.kindConsult',
  review: 'officeMessageLine.kindReview',
}

export function kindLabel(kind: OfficeEventKind, t: Translate = defaultT): string {
  return t(KIND_LABEL_KEY[kind])
}

export function messageLine(m: OfficeMessage, t: Translate = defaultT): string {
  const b = m.body
  switch (m.kind) {
    case 'ceo':
      return b.text ?? ''
    case 'assignment': {
      // v15: `pic` names the staffer responsible for the whole task. The backend's
      // `summary` may already lead with "PIC: x" — only prefix here when it doesn't
      // (older events / other writers), so the line never reads "PIC: x — PIC: x — …".
      const base = t('officeMessageLine.assignmentLine', {
        taskTitle: b.task_title ?? '',
        summary: b.summary ?? '',
        stepCount: b.step_count ?? 0,
      })
      const pic = b.pic ?? ''
      return pic && !(b.summary ?? '').includes(`PIC: ${pic}`)
        ? `${base}${t('officeMessageLine.picSuffix', { pic })}`
        : base
    }
    case 'step_status': {
      const phaseKey = b.phase ? PHASE_LABEL[b.phase] : undefined
      const phaseLabel = phaseKey ? t(phaseKey) : undefined
      const suffix = phaseLabel ? ` (${phaseLabel})` : ''
      // v34 P2: the one non-self-explanatory status value gets a human label — the
      // rest (started/done/failed) read fine as-is and stay byte-identical.
      const status = b.status === 'waiting_clarify' ? t('officeMessageLine.waitingClarify') : (b.status ?? '')
      return t('officeMessageLine.stepStatusLine', {
        taskTitle: b.task_title ?? '', stepTitle: b.step_title ?? '', status, suffix,
      })
    }
    case 'handoff':
      // v17: the feed is an index, not a report viewer — the FULL result lives in the
      // Outputs column (artifact viewer), so the line stays a fixed short notice.
      return t('officeMessageLine.handoffLine', {
        taskTitle: b.task_title ?? '', stepTitle: b.step_title ?? '',
      })
    case 'milestone':
      return t('officeMessageLine.milestoneLine', { taskTitle: b.task_title ?? '', message: b.message ?? '' })
    case 'consult':
      return t('officeMessageLine.consultLine', {
        from: b.from ?? '', to: b.to ?? '',
        question: b.question_summary ?? '', answer: b.answer_summary ?? '',
      })
    case 'review': {
      const verdictLabel = b.verdict === 'passed'
        ? t('officeMessageLine.verdictPassed')
        : t('officeMessageLine.verdictFailed', { n: b.failure_count ?? 0 })
      // v34 P5: per-criterion count when the verdict graded a checklist (0 = pre-P5
      // event or no criteria on the step — omit rather than show "0/0").
      const checklist = b.criteria_total
        ? t('officeMessageLine.criteriaSuffix', { passed: b.criteria_passed ?? 0, total: b.criteria_total })
        : ''
      return t('officeMessageLine.reviewLine', {
        taskTitle: b.task_title ?? '', stepTitle: b.step_title ?? '', verdict: verdictLabel, checklist,
      })
    }
    default:
      return ''
  }
}
