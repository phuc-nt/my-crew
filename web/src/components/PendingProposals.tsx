// Pending Lớp B proposals (read-only here; the approve/reject actions live in the S4 ops
// view). Shows id/reason/status/action_summary — the action is summarized, never raw args.
import type { Proposal } from '../types'

export function PendingProposals({ pending }: { pending: Proposal[] }) {
  if (pending.length === 0) return <p className="muted">No pending proposals.</p>
  return (
    <div className="table-scroll">
    <table className="proposals-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Action</th>
          <th>Reason</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {pending.map((p) => (
          <tr key={p.id}>
            <td>{p.id}</td>
            <td>{p.action_summary}</td>
            <td>{p.reason}</td>
            <td>{p.status}</td>
            <td>{p.created_at}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
