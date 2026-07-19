// Run history list (newest-first, allowlisted run-events from /api/runs). Status-styled.
import { AUDIENCE_LABEL, KIND_LABEL, RUN_STATUS_LABEL, formatCost, formatDateTime, labelFor } from '../labels'
import type { RunEvent } from '../types'

export function RunList({ runs }: { runs: RunEvent[] }) {
  if (runs.length === 0) return <p>Chưa có lần chạy nào.</p>
  return (
    <div className="table-scroll">
    <table className="runs-table">
      <thead>
        <tr>
          <th>Thời gian</th>
          <th>Loại</th>
          <th>Đối tượng</th>
          <th>Trạng thái</th>
          <th>Chi phí</th>
          <th>Đã gửi</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r, i) => (
          <tr key={`${r.ts}-${i}`}>
            <td>{formatDateTime(r.ts) || r.ts}</td>
            <td>{labelFor(KIND_LABEL, r.kind)}</td>
            <td>{labelFor(AUDIENCE_LABEL, r.audience)}</td>
            <td className={`status status-${r.status}`}>{labelFor(RUN_STATUS_LABEL, r.status)}</td>
            <td>{formatCost(r.cost_usd)}</td>
            <td>{r.delivered ? '✓' : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
