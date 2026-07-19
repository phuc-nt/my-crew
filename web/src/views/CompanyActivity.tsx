// "Hoạt động" (route /company-activity, v31 P1): the fleet-wide post-hoc audit surface of
// autonomy-first — every agent's gateway decisions, runs, and team-step attempts in one
// newest-first table. CEO-primary nav (NOT gated behind high ui-mode: reviewing what the
// autonomous fleet did is the core low-tech workflow). Read-only; consumes
// /api/company/activity which projects to a server-side allowlist.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import type { CompanyActivityItem, CompanyActivityPayload } from '../types'

const PAGE = 50

const SOURCE_LABEL: Record<CompanyActivityItem['source'], string> = {
  audit: 'Rào chắn',
  run: 'Lượt chạy',
  capture: 'Việc đội',
}

const DAY_CHOICES = [
  { days: 1, label: 'Hôm nay' },
  { days: 7, label: '7 ngày' },
  { days: 31, label: '31 ngày' },
]

function sinceIso(days: number): string {
  return new Date(Date.now() - days * 24 * 3600 * 1000).toISOString()
}

// One human line per item, per source — mirrors the ops-chat summarizer's projection.
function describe(it: CompanyActivityItem): string {
  if (it.source === 'audit') {
    const head = [it.action_type, it.tool].filter(Boolean).join(':')
    // v46: show the actor when it differs from the log owner (agent_id) — e.g. a coordinated
    // or deep_team action performed by another agent under this agent's context.
    const who = it.actor && it.actor !== it.agent_id ? ` [bởi ${it.actor}]` : ''
    return (it.reason ? `${head} — ${it.reason}` : head) + who
  }
  if (it.source === 'run') {
    const head = `chạy '${it.kind ?? '?'}' (${it.audience ?? '?'})`
    return it.delivered ? `${head} — đã gửi` : head
  }
  return `bước ${it.step_type ?? '?'} trên ${it.engine ?? '?'} (việc ${it.task_id ?? '?'})`
}

function statusOf(it: CompanyActivityItem): string {
  return (it.source === 'audit' ? it.verdict : it.status) ?? ''
}

export function CompanyActivity() {
  const [data, setData] = useState<CompanyActivityPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [agent, setAgent] = useState('')
  const [verdict, setVerdict] = useState('')
  const [days, setDays] = useState(7)
  const [limit, setLimit] = useState(PAGE)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getCompanyActivity({
        limit,
        since: sinceIso(days),
        agent: agent || undefined,
        verdict: verdict || undefined,
      })
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [agent, verdict, days, limit])

  useEffect(() => {
    load()
  }, [load])

  const items = data?.items ?? []
  return (
    <section>
      <PageHeader title="Hoạt động công ty" />
      <p>Mọi hành động các agent đã tự làm — quyết định rào chắn, lượt chạy, bước việc đội.</p>
      <div className="filter-row">
        <label>
          Agent{' '}
          <select value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">Tất cả</option>
            {(data?.agents ?? []).map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>{' '}
        <label>
          Kết quả{' '}
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="">Tất cả</option>
            <option value="allow">Được phép</option>
            <option value="deny">Bị chặn</option>
            <option value="dry_run">Chạy thử</option>
          </select>
        </label>{' '}
        <label>
          Thời gian{' '}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAY_CHOICES.map((c) => (
              <option key={c.days} value={c.days}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {verdict && (
        <p className="muted">
          Bộ lọc kết quả chỉ áp dụng cho quyết định rào chắn — lượt chạy và bước việc đội
          tạm ẩn khi đang lọc.
        </p>
      )}
      {loading && <p>Đang tải…</p>}
      {error && <p className="error">Lỗi: {error}</p>}
      {!loading && !error && items.length === 0 && (
        <EmptyState>Chưa có hoạt động nào trong khoảng thời gian này.</EmptyState>
      )}
      {(data?.skipped.length ?? 0) > 0 && (
        <p className="error">Không đọc được dữ liệu của: {data?.skipped.join(', ')}</p>
      )}
      {items.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Lúc</th>
              <th>Agent</th>
              <th>Loại</th>
              <th>Hành động</th>
              <th>Kết quả</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={`${it.ts}-${it.agent_id}-${i}`}>
                <td>{(it.ts ?? '').slice(0, 19).replace('T', ' ')}</td>
                <td>{it.agent_id}</td>
                <td>{SOURCE_LABEL[it.source] ?? it.source}</td>
                <td>{describe(it)}</td>
                <td>{statusOf(it)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {items.length >= limit && (
        <Button variant="ghost" onClick={() => setLimit((n) => n + PAGE)}>
          Xem thêm
        </Button>
      )}
    </section>
  )
}
