// Recent guardrail/audit events table (already-redacted, allowlisted rows from /api/audit).
import type { AuditRow } from '../types'

export function AuditTable({ rows }: { rows: AuditRow[] }) {
  if (rows.length === 0) return <p>No audit events yet.</p>
  return (
    <div className="table-scroll">
    <table className="audit-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Type</th>
          <th>Tool</th>
          <th>Verdict</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.timestamp}-${i}`}>
            <td>{r.timestamp}</td>
            <td>{r.action_type}</td>
            <td>{r.tool}</td>
            <td className={`verdict verdict-${r.verdict}`}>{r.verdict}</td>
            <td>{r.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
