// v94: "vì sao + làm gì tiếp" for every failure the CEO can see in the app — a chat row
// that went red, a stalled board card, a task's terminal failure mode. One table, so
// the same defect reads the same on every surface. The ids are the backend's own
// vocabulary (task_failure_mode.py modes, gateway outcomes, step statuses); an id this
// build does not know yields no guidance rather than a wrong one.
import type { UiKey } from '../../i18n/dictionary'

export type FailureCase =
  | 'cost_cap'
  | 'plan_mismatch'
  | 'verification_exhausted'
  | 'dead_step'
  | 'step_exhausted'
  | 'external_deny'
  | 'review_failed'
  | 'step_failed'
  | 'step_timeout'

const CASES: ReadonlySet<string> = new Set<FailureCase>([
  'cost_cap', 'plan_mismatch', 'verification_exhausted', 'dead_step', 'step_exhausted',
  'external_deny', 'review_failed', 'step_failed', 'step_timeout',
])

export interface FailureGuidance {
  why: string
  next: string
}

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

/** Guidance for a known case; undefined for anything else (render nothing). */
export function failureGuidance(t: Translate, id: string | undefined): FailureGuidance | undefined {
  if (!id || !CASES.has(id)) return undefined
  return {
    why: t(`failureGuide.${id}.why` as UiKey),
    next: t(`failureGuide.${id}.next` as UiKey),
  }
}

/** Map a thread row's (kind, status/outcome/verdict) onto a case — the chat surface. */
export function failureCaseForRow(
  kind: string, body: { status?: string; outcome?: string; verdict?: string },
): FailureCase | undefined {
  if (kind === 'external_action' && body.outcome === 'deny') return 'external_deny'
  if (kind === 'review' && body.verdict && body.verdict !== 'passed') return 'review_failed'
  if (kind === 'step_status' && body.status === 'failed') return 'step_failed'
  if (kind === 'step_status' && body.status === 'timeout') return 'step_timeout'
  return undefined
}

/** A stalled task with a dead step vs. one whose review rounds ran out — the board
 *  card and the detail page only know which of the two it is, not the failure mode. */
export function failureCaseForStall(hasDeadStep: boolean): FailureCase {
  return hasDeadStep ? 'step_failed' : 'verification_exhausted'
}
