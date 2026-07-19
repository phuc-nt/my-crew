// v9 P1 — shared i18n labels for CEO-facing views (DRY; extends the STATUS_LABEL pattern
// from Tasks.tsx). Every lookup goes through labelFor() so a missing/undefined key renders a
// safe "—" instead of blank (a run event can have kind/status undefined — Team uses `?? '?'`).

// Run-event status vocab (verify worker.py) — 5 terminal + a few pseudo-kind statuses.
export const RUN_STATUS_LABEL: Record<string, string> = {
  delivered: 'đã gửi',
  not_delivered: 'chưa gửi',
  error: 'lỗi',
  load_error: 'lỗi cấu hình',
  interrupted: 'chờ duyệt',
  // pseudo-kinds (inbox/tasks/ops-alerts runners)
  no_mentions: 'không có câu hỏi mới',
  no_tasks: 'không có việc',
  no_new_alerts: 'không có cảnh báo mới',
  bootstrapped: 'đã khởi tạo',
  writes_disabled: 'ghi bị tắt',
}

export const KIND_LABEL: Record<string, string> = {
  daily: 'Báo cáo hằng ngày',
  weekly: 'Báo cáo tuần',
  okr: 'Báo cáo OKR',
  resource: 'Báo cáo nhân sự & chi phí',
  inbox: 'Trả lời câu hỏi',
  tasks: 'Việc đã giao',
  'ops-alerts': 'Cảnh báo đội',
  'project-rollup': 'Tổng quan dự án',
  'cost-rollup': 'Chi phí toàn đội',
  'guardrail-health': 'Sức khoẻ rào chắn',
  'audit-digest': 'Nhật ký hoạt động',
}

export const VERDICT_LABEL: Record<string, string> = {
  allow: 'đã chạy',
  deny: 'bị chặn',
  pending: 'chờ duyệt',
  reject: 'đã từ chối',
  dry_run: 'chạy thử',
  skipped: 'bỏ qua',
}

// Audience of a run/report (internal team vs external stakeholders). Used by the advanced
// Trigger form + run tables (v10 M25).
export const AUDIENCE_LABEL: Record<string, string> = {
  internal: 'nội bộ',
  external: 'đối ngoại',
}

/** Look up a label; a missing/undefined key returns "—" (never a blank cell). */
export function labelFor(map: Record<string, string>, key: string | undefined | null): string {
  if (!key) return '—'
  return map[key] ?? key // unknown-but-present key → show it raw rather than hide
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
