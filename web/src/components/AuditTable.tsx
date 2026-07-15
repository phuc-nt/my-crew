// Recent guardrail/audit events table (already-redacted, allowlisted rows from /api/audit).
import { VERDICT_LABEL, formatDateTime, labelFor } from '../labels'
import type { AuditRow } from '../types'

export function AuditTable({ rows }: { rows: AuditRow[] }) {
  if (rows.length === 0) return <p>Chưa có sự kiện nào.</p>
  return (
    <div className="table-scroll">
    <table className="audit-table">
      <thead>
        <tr>
          <th>Thời gian</th>
          <th>Ai thực hiện</th>
          <th>Loại</th>
          <th>Công cụ</th>
          <th>Kết quả</th>
          <th>Lý do</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.timestamp}-${i}`}>
            <td>{formatDateTime(r.timestamp) || r.timestamp}</td>
            {/* v46: actor = agent that acted; operator/CLI actions store "" → render "—" */}
            <td>{r.actor || '—'}</td>
            <td>{r.action_type}</td>
            <td>{r.tool}</td>
            <td className={`verdict verdict-${r.verdict}`}>{labelFor(VERDICT_LABEL, r.verdict)}</td>
            <td>{r.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
