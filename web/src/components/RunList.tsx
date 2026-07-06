// Run history list (newest-first, allowlisted run-events from /api/runs). Status-styled.
import type { RunEvent } from '../types'

export function RunList({ runs }: { runs: RunEvent[] }) {
  if (runs.length === 0) return <p>No runs yet.</p>
  return (
    <div className="table-scroll">
    <table className="runs-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Kind</th>
          <th>Audience</th>
          <th>Status</th>
          <th>Cost</th>
          <th>Delivered</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r, i) => (
          <tr key={`${r.ts}-${i}`}>
            <td>{r.ts}</td>
            <td>{r.kind}</td>
            <td>{r.audience}</td>
            <td className={`status status-${r.status}`}>{r.status}</td>
            <td>{r.cost_usd != null ? `$${r.cost_usd.toFixed(4)}` : '—'}</td>
            <td>{r.delivered ? '✓' : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
