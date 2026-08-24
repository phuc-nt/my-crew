// Shared office-event → one-line text rendering (v15): extracted from OfficeRoom.tsx so
// the unified office screen's activity feed and the timeline tab render an event
// IDENTICALLY (one vocabulary, one place to extend). Pure functions — no hooks, no r3f —
// unit-testable in plain vitest. PHASE_LABEL is shared with the 3D bubble via
// phase-labels.ts (same closed-set backend vocabulary, one source of truth) — importing
// it from the bubble itself would pull three.js into the eager bundle.
//
// v53 i18n: both kindLabel and messageLine take an optional `t` (useLanguage()'s
// translate fn), defaulting to DICT.vi (same fallback pattern as agent-desk.tsx) for any
// caller without language-context access.
import { DICT } from '../../i18n/dictionary'
import type { UiKey } from '../../i18n/dictionary'
import type { OfficeEventKind, OfficeMessage } from '../../types'
import { PHASE_LABEL } from './phase-labels'

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
  // v54: Action Gateway outcome bridge — label only; `messageLine`'s `default: return ''`
  // still covers rendering (FE display of this kind is out of scope for this phase).
  external_action: 'officeMessageLine.kindExternalAction',
  // v80 P4: live in-step activity (tool name + counter only — args/results never
  // reach the room, see office_event_projection.py's `step_activity` branch).
  step_activity: 'officeMessageLine.kindStepActivity',
  advisor: 'officeMessageLine.kindAdvisor',
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
      // v34 P2: status values that do not read as plain language get a human label —
      // the rest (started/done/failed) read fine as-is and stay byte-identical.
      const STATUS_LABEL: Record<string, UiKey> = {
        waiting_clarify: 'officeMessageLine.waitingClarify',
        needs_decision: 'officeMessageLine.needsDecision',
      }
      const labelKey = b.status ? STATUS_LABEL[b.status] : undefined
      const status = labelKey ? t(labelKey) : (b.status ?? '')
      return t('officeMessageLine.stepStatusLine', {
        taskTitle: b.task_title ?? '', stepTitle: b.step_title ?? '', status, suffix,
      })
    }
    case 'advisor':
      // The note IS the payload — an advisor's whole product is its one short remark,
      // so unlike the structured kinds there is nothing to compose here. Severity
      // rides in the status tone (nit = neutral, concern = warn), not the text.
      return b.message ?? ''
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
    case 'external_action': {
      // v54 P3: "actor → tool detail · outcome" — detail is already a short non-content
      // target (see OfficeEventBody.detail's docstring), so this is a straight join, no
      // truncation logic of its own.
      const outcomeLabel = b.outcome === 'allow'
        ? t('officeMessageLine.outcomeAllow')
        : b.outcome === 'deny'
          ? t('officeMessageLine.outcomeDeny')
          : (b.outcome ?? '')
      // Live-UAT dedup: the feed row already shows the actor as its author chip, so the
      // line starts at the tool; and some gateway tool ids embed their target (e.g.
      // "telegram:<chat>"), in which case repeating `detail` would print it twice.
      const tool = b.tool ?? ''
      const detail = b.detail && !tool.includes(b.detail) ? ` ${b.detail}` : ''
      return t('officeMessageLine.externalActionLine', {
        actor: b.actor ?? '', tool, detail, outcome: outcomeLabel,
      })
    }
    case 'step_activity': {
      // v80 P4: "web_search (3)" while a tool is firing, "đang viết…" while the model
      // writes. The agent id already shows as the row's author chip, so the line
      // carries only the activity itself.
      if (b.phase === 'writing') return t('officeMessageLine.stepActivityWriting')
      return t('officeMessageLine.stepActivityToolLine', {
        tool: b.tool ?? '', count: b.count ?? 0,
      })
    }
    default:
      return ''
  }
}

// v54 P3: presentation-only tone for an external_action line's outcome — mirrors
// feedStatusClass's per-kind flavor (allow=ok, deny=danger, everything else neutral;
// pending/dry_run/skipped/reject read fine unstyled — no dedicated tone requested).
export function externalActionTone(outcome: string | undefined): 'ok' | 'danger' | 'neutral' {
  if (outcome === 'allow') return 'ok'
  if (outcome === 'deny') return 'danger'
  return 'neutral'
}
