// Dropdown to pick the active agent. Reads/writes the shared agent context.
import { useAgent } from '../agent-context'

export function AgentPicker() {
  const { agents, selected, setSelected, loading } = useAgent()
  if (loading) return <span className="agent-picker">loading agents…</span>
  if (agents.length === 0) return <span className="agent-picker">no agents</span>
  return (
    <label className="agent-picker">
      Agent:{' '}
      <select value={selected ?? ''} onChange={(e) => setSelected(e.target.value)}>
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} ({a.id})
          </option>
        ))}
      </select>
    </label>
  )
}
