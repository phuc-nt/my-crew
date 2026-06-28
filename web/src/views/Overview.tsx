// Overview: the agent list (replaces the htmx index). Renders id/name/enabled + last-run
// status from /api/agents. The first end-to-end proof: FastAPI static → React → /api/agents.
import { useAgent } from '../agent-context'

export function Overview() {
  const { agents, loading, error } = useAgent()
  if (loading) return <p>Loading agents…</p>
  if (error) return <p className="error">Error: {error}</p>
  if (agents.length === 0) return <p>No agents registered.</p>

  return (
    <section>
      <h2>Agents</h2>
      <table className="agents-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Enabled</th>
            <th>Last run</th>
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
                  ? `${a.last_run.kind ?? '?'} · ${a.last_run.status ?? '?'}`
                  : 'no runs yet'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
