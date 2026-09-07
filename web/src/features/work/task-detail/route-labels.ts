// Reader-facing names for the routing vocabulary the backend stamps on a task
// (mode / source / shape / effort / failure mode). Ids stay English on the wire; an id
// this build does not know falls back to itself so a route written by a newer release
// still shows something rather than "—".
import type { UiKey } from '../../../i18n/dictionary'

const KNOWN: Record<string, readonly string[]> = {
  mode: ['sprint', 'team'],
  source: ['prefix', 'refusal', 'heuristic', 'downgrade', 'upgrade', 'unmeasurable', 'shape'],
  shape: ['fanout', 'do_review', 'permission_chain', 'custom'],
  effort: ['low', 'medium', 'high'],
  failure: ['cost_cap', 'plan_mismatch', 'verification_exhausted', 'dead_step', 'step_exhausted'],
}

export type RouteField = keyof typeof KNOWN

export function routeLabel(
  t: (key: UiKey) => string, field: RouteField, id: string,
): string {
  if (!id) return '—'
  return KNOWN[field].includes(id) ? t(`route.${field}.${id}` as UiKey) : id
}
