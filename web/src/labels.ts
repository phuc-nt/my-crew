// v9 P1 — shared i18n labels for CEO-facing views (DRY; extends the STATUS_LABEL pattern
// from Tasks.tsx). Every lookup goes through labelFor() so a missing/undefined key renders a
// safe "—" instead of blank (a run event can have kind/status undefined — Team uses `?? '?'`).
//
// v53 i18n: these are FE-static maps over backend enum values (the enum values themselves
// — 'delivered', 'daily', etc — are wire vocabulary and never translate; only the human
// label does). Each map is now `Record<string, UiKey>`; labelFor() takes an optional `t`
// (useLanguage()'s translate fn) and falls back to DICT.vi when omitted, matching the
// pattern in office-shared/office-message-line.ts.
import { DICT } from './i18n/dictionary'
import type { UiKey } from './i18n/dictionary'

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

// Run-event status vocab (verify worker.py) — 5 terminal + a few pseudo-kind statuses.
export const RUN_STATUS_LABEL: Record<string, UiKey> = {
  delivered: 'labels.runStatus.delivered',
  not_delivered: 'labels.runStatus.notDelivered',
  error: 'labels.runStatus.error',
  load_error: 'labels.runStatus.loadError',
  interrupted: 'labels.runStatus.interrupted',
  // pseudo-kinds (inbox/tasks/ops-alerts runners)
  no_mentions: 'labels.runStatus.noMentions',
  no_tasks: 'labels.runStatus.noTasks',
  no_new_alerts: 'labels.runStatus.noNewAlerts',
  bootstrapped: 'labels.runStatus.bootstrapped',
  writes_disabled: 'labels.runStatus.writesDisabled',
}

export const KIND_LABEL: Record<string, UiKey> = {
  daily: 'labels.kind.daily',
  weekly: 'labels.kind.weekly',
  okr: 'labels.kind.okr',
  resource: 'labels.kind.resource',
  inbox: 'labels.kind.inbox',
  tasks: 'labels.kind.tasks',
  'ops-alerts': 'labels.kind.opsAlerts',
  'project-rollup': 'labels.kind.projectRollup',
  'cost-rollup': 'labels.kind.costRollup',
  'guardrail-health': 'labels.kind.guardrailHealth',
  'audit-digest': 'labels.kind.auditDigest',
}

export const VERDICT_LABEL: Record<string, UiKey> = {
  allow: 'labels.verdict.allow',
  deny: 'labels.verdict.deny',
  pending: 'labels.verdict.pending',
  reject: 'labels.verdict.reject',
  dry_run: 'labels.verdict.dryRun',
  skipped: 'labels.verdict.skipped',
}

// Audience of a run/report (internal team vs external stakeholders). Used by the advanced
// Trigger form + run tables (v10 M25).
export const AUDIENCE_LABEL: Record<string, UiKey> = {
  internal: 'labels.audience.internal',
  external: 'labels.audience.external',
}

/** Look up a label; a missing/undefined key returns "—" (never a blank cell). */
export function labelFor(
  map: Record<string, UiKey>,
  key: string | undefined | null,
  t?: Translate,
): string {
  if (!key) return t ? t('labels.missing') : DICT.vi['labels.missing']
  const dictKey = map[key]
  if (!dictKey) return key // unknown-but-present key → show it raw rather than hide
  return t ? t(dictKey) : DICT.vi[dictKey]
}

/** ISO datetime → "HH:mm dd/MM" in VN locale. Empty/invalid input → "". */
export function formatDateTime(iso: string | undefined | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: '2-digit',
  })
}

const _CRON_DAYS = ['Chủ nhật', 'Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7']

/** A 5-field cron → a human Vietnamese description. Unparseable → the raw cron. */
export function formatCron(cron: string | undefined | null): string {
  if (!cron || !cron.trim()) return 'chạy thủ công'
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hour, , , dow] = parts
  const h = Number(hour)
  const m = Number(min)
  if (Number.isNaN(h) || Number.isNaN(m)) return cron
  const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  if (dow === '*') return `${time} mỗi ngày`
  const days = dow
    .split(',')
    .map((d) => _CRON_DAYS[Number(d) % 7])
    .filter(Boolean)
    .join(', ')
  return days ? `${time} ${days}` : `${time} (${cron})`
}

// v53: ONE cost format app-wide (was ~7 inline toFixed variants). LLM step costs are
// sub-cent — below $1 keep 4 decimals ($0.0034); from $1 up 2 decimals ($2.70). Caps
// and totals share the same rule so "spent/cap" pairs read consistently.
export function formatCost(usd: number | undefined | null): string {
  if (usd == null || !Number.isFinite(usd)) return '—'
  return usd < 1 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`
}
