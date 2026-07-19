// Overview: the agent list (replaces the htmx index). Renders id/name/enabled + last-run
// status from /api/agents. The first end-to-end proof: FastAPI static → React → /api/agents.
import { useAgent } from '../agent-context'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { KIND_LABEL, RUN_STATUS_LABEL, labelFor } from '../labels'

export function Overview() {
  const { agents, loading, error } = useAgent()
  if (loading) return <p>Đang tải…</p>
  if (error) return <p className="error">Lỗi: {error}</p>
  if (agents.length === 0) return <EmptyState>Chưa có nhân sự ảo nào.</EmptyState>

  return (
    <section>
      <PageHeader title="Tổng quan đội" />
      {/* Advanced (technical) view — a distinct class so it does NOT inherit the mobile
          card-list transform meant for the CEO tables; it just scrolls horizontally. */}
      <div className="table-scroll">
        <table className="agents-table-advanced">
          <thead>
            <tr>
              <th>Mã</th>
              <th>Tên</th>
              <th>Bật</th>
              <th>Lần chạy gần nhất</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td>{a.id}</td>
                <td>{a.name}</td>
                <td>{a.enabled ? '✓' : '—'}</td>
                <td>
                  {a.last_run
                    ? `${labelFor(KIND_LABEL, a.last_run.kind)} · ${labelFor(RUN_STATUS_LABEL, a.last_run.status)}`
                    : 'chưa chạy lần nào'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
