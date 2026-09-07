// The attention center's item model: one severity-ranked list built from the signals
// the backend already exposes (pending approvals, agent questions, stalled tasks,
// budget ratios, coordinator heartbeat, fleet alerts, template upgrades).
//
// Pure functions only — no queries, no React — so the ranking and the dismissal rules
// are testable with plain fixtures. The hook in use-attention-items.ts feeds real data.
import type {
  ClarifyQuestion,
  CoordinatorHealthPayload,
  FleetApprovalItem,
  FleetBudgetPayload,
  TeamAlert,
  TeamBoardLane,
  TemplateStatusRow,
} from '../../types'
import type { UiKey } from '../../i18n/dictionary'

export type AttentionSeverity = 'error' | 'warning' | 'info'

export interface AttentionItem {
  /** Stable identity — the dismissal key. Survives refetches of the same signal. */
  id: string
  /** Changes when the item's substance changes, which un-dismisses it. */
  fingerprint: string
  severity: AttentionSeverity
  title: string
  detail?: string
  /** Deep link to the surface that resolves the item. */
  to: string
}

export interface AttentionSources {
  approvals?: FleetApprovalItem[]
  clarify?: ClarifyQuestion[]
  lanes?: TeamBoardLane[]
  budget?: FleetBudgetPayload
  coordinator?: CoordinatorHealthPayload
  alerts?: TeamAlert[]
  templates?: TemplateStatusRow[]
}

export type Translate = (key: UiKey, params?: Record<string, string | number>) => string

const SEVERITY_RANK: Record<AttentionSeverity, number> = { error: 0, warning: 1, info: 2 }

/** Fleet alerts carry a machine `kind`; each gets its own short title. */
const ALERT_TITLE_KEY: Record<TeamAlert['kind'], UiKey> = {
  budget: 'attention.alertKind.budget',
  approval_stuck: 'attention.alertKind.approval_stuck',
  deny_spike: 'attention.alertKind.deny_spike',
  missed_schedule: 'attention.alertKind.missed_schedule',
  failing: 'attention.alertKind.failing',
}

const BUDGET_WARN_RATIO = 0.8

function money(n: number): string {
  return n.toFixed(2)
}

/**
 * Build the ranked list. Order is severity first (error > warning > info), then source
 * order within a severity, so the most urgent thing is always the first row.
 */
export function buildAttentionItems(src: AttentionSources, t: Translate): AttentionItem[] {
  const items: AttentionItem[] = []

  if (src.coordinator && !src.coordinator.alive) {
    items.push({
      id: 'coordinator',
      fingerprint: src.coordinator.reason,
      severity: 'error',
      title: t('attention.coordinatorDown'),
      detail: src.coordinator.hint || undefined,
      to: '/system?tab=settings',
    })
  }

  for (const lane of src.lanes ?? []) {
    for (const card of lane.cards) {
      if (card.status !== 'stalled') continue
      items.push({
        id: `stalled:${card.task_id}`,
        fingerprint: `${card.stalled_step ?? ''}:${card.steps_done}`,
        severity: 'error',
        title: t('attention.stalled', { title: card.title }),
        detail: card.stalled_step
          ? t('attention.stalledStep', { step: card.stalled_step })
          : undefined,
        to: `/work/task/${encodeURIComponent(card.room_id)}`,
      })
    }
  }

  for (const row of src.budget?.agents ?? []) {
    if (row.ratio < BUDGET_WARN_RATIO) continue
    const over = row.ratio >= 1
    const pct = Math.round(row.ratio * 100)
    items.push({
      id: `budget:${row.agent_id}`,
      // Only the band is in the fingerprint: a dismissed "near cap" stays dismissed while
      // spend creeps, but comes back the moment the agent crosses the cap.
      fingerprint: over ? 'over' : 'near',
      severity: over ? 'error' : 'warning',
      title: t(over ? 'attention.budgetOver' : 'attention.budgetNear', {
        agent: row.agent_id,
        pct,
      }),
      detail: t('attention.budgetDetail', { spent: money(row.spent_usd), cap: money(row.cap_usd) }),
      to: `/team/${encodeURIComponent(row.agent_id)}?tab=budget`,
    })
  }

  for (const al of src.alerts ?? []) {
    const key = ALERT_TITLE_KEY[al.kind] ?? 'attention.alertKind.generic'
    items.push({
      id: `alert:${al.kind}:${al.agent_id}`,
      fingerprint: al.message,
      severity: al.severity === 'high' ? 'error' : 'warning',
      title: t(key, { agent: al.agent_id }),
      detail: al.message,
      to: `/team/${encodeURIComponent(al.agent_id)}`,
    })
  }

  for (const ap of src.approvals ?? []) {
    items.push({
      id: `approval:${ap.agent_id}:${ap.id}`,
      fingerprint: ap.created_at,
      severity: 'warning',
      title: t('attention.approval', { agent: ap.agent_id }),
      detail: ap.reason,
      to: '/work',
    })
  }

  for (const q of src.clarify ?? []) {
    items.push({
      id: `clarify:${q.id}`,
      fingerprint: q.asked_at,
      severity: 'warning',
      title: t('attention.clarify', { agent: q.agent_id }),
      detail: q.question,
      to: '/chat',
    })
  }

  for (const row of src.templates ?? []) {
    if (!row.upgradable) continue
    items.push({
      id: `template:${row.agent_id}`,
      fingerprint: `${row.applied_version}->${row.latest_version}`,
      severity: 'info',
      title: t('attention.templateUpgrade', { agent: row.agent_id }),
      detail: t('attention.templateVersions', {
        from: row.applied_version,
        to: row.latest_version,
      }),
      to: '/team',
    })
  }

  // Stable sort: JS Array#sort is stable, so ties keep source order.
  return items.sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
}

// ── Dismissal store ─────────────────────────────────────────────────────────────
//
// id → fingerprint. An item is hidden only while its fingerprint still matches what
// was dismissed; a changed message or a crossed threshold surfaces it again.

export const DISMISSED_STORAGE_KEY = 'my-crew.attention.dismissed'

export type DismissedMap = Record<string, string>

export function readDismissed(): DismissedMap {
  try {
    const raw = localStorage.getItem(DISMISSED_STORAGE_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const out: DismissedMap = {}
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'string') out[k] = v
    }
    return out
  } catch {
    return {}
  }
}

export function writeDismissed(map: DismissedMap): void {
  try {
    localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // Storage may be unavailable (private mode, quota); the in-memory state still works.
  }
}

export function isDismissed(item: AttentionItem, dismissed: DismissedMap): boolean {
  return dismissed[item.id] === item.fingerprint
}
