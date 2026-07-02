// Team view (route /team): all agents with lifecycle controls (pause/resume, delete) +
// the integration health panel. Statuses (budget, pending approvals) are fetched lazily
// per-agent after the agent list loads, mirroring how other views fetch per-selected-agent
// data via api.getAgentStatus. Delete requires the existing ConfirmDialog-style two-step
// confirm; the `default` agent's Delete action is hidden (backend also 400s it).
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import { IntegrationHealthPanel } from '../components/IntegrationHealthPanel'
import type { AgentStatus, AgentSummary } from '../types'

export function Team() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [statuses, setStatuses] = useState<Record<string, AgentStatus>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [opError, setOpError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const [deletedNote, setDeletedNote] = useState<string | null>(null)
  // agent id -> "profile still disables it" notice after a Resume the profile vetoes
  // (PATCH .../enabled returns effective_enabled=false even though enabled=true).
  const [profileDisabledNotice, setProfileDisabledNotice] = useState<Record<string, boolean>>({})

  const loadAgents = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getAgents()
      .then((list) => {
        setAgents(list)
        for (const a of list) {
          api
            .getAgentStatus(a.id)
            .then((s) => setStatuses((prev) => ({ ...prev, [a.id]: s })))
            .catch(() => undefined) // a single agent's status failing shouldn't break the table
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed to load agents'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadAgents()
  }, [loadAgents])

  async function toggleEnabled(agent: AgentSummary) {
    setBusyId(agent.id)
    setOpError(null)
    try {
      const res = await api.setAgentEnabled(agent.id, !agent.enabled)
      // Don't trust the optimistic `enabled` value alone — a Resume can flip the
      // registry (enabled: true) while the profile still vetoes the agent
      // (effective_enabled: false). Re-fetch the real list so the table reflects the
      // service gate's actual state, and surface a per-row notice for that case.
      setProfileDisabledNotice((prev) => {
        const next = { ...prev }
        if (res.enabled && !res.effective_enabled) next[agent.id] = true
        else delete next[agent.id]
        return next
      })
      await refreshAgentsOnly()
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'toggle failed')
    } finally {
      setBusyId(null)
    }
  }

  async function refreshAgentsOnly() {
    const list = await api.getAgents()
    setAgents(list)
  }

  async function confirmDelete(id: string) {
    setBusyId(id)
    setOpError(null)
    try {
      await api.deleteAgent(id)
      setAgents((prev) => prev.filter((a) => a.id !== id))
      setProfileDisabledNotice((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      setConfirmingDelete(null)
      setDeletedNote(`Deleted ${id}. profiles/${id}/ is kept on disk as an archive.`)
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'delete failed')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section>
      <IntegrationHealthPanel />

      <h2>
        Team <Link to="/create">New agent</Link>
      </h2>
      {opError && <p className="error">Error: {opError}</p>}
      {deletedNote && <p className="ok">{deletedNote}</p>}
      {loading && <p>Loading agents…</p>}
      {error && <p className="error">Error: {error}</p>}
      {!loading && !error && agents.length === 0 && <p className="muted">No agents registered.</p>}
      {!loading && !error && agents.length > 0 && (
        <table className="agents-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Enabled</th>
              <th>Last run</th>
              <th>Budget</th>
              <th>Pending approvals</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const status = statuses[a.id]
              return (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td>{a.name}</td>
                  <td>
                    {a.enabled ? '✓' : '—'}
                    {profileDisabledNotice[a.id] && (
                      <div className="error health-detail">
                        Profile still disabled — enable it in Config
                      </div>
                    )}
                  </td>
                  <td>
                    {a.last_run ? `${a.last_run.kind ?? '?'} · ${a.last_run.status ?? '?'}` : 'no runs yet'}
                  </td>
                  <td>{status ? `$${status.budget.spent.toFixed(2)} / $${status.budget.cap.toFixed(2)}` : '…'}</td>
                  <td>{status ? status.pending_approvals : '…'}</td>
                  <td>
                    <button type="button" disabled={busyId === a.id} onClick={() => toggleEnabled(a)}>
                      {a.enabled ? 'Pause' : 'Resume'}
                    </button>{' '}
                    {a.id !== 'default' && (
                      <button
                        type="button"
                        disabled={busyId === a.id}
                        onClick={() => setConfirmingDelete(a.id)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {confirmingDelete && (
        <div className="confirm-dialog" role="dialog" aria-label="Confirm delete">
          <h3>Delete agent {confirmingDelete}?</h3>
          <p>The registry entry is removed. profiles/{confirmingDelete}/ stays on disk as an archive.</p>
          <button type="button" disabled={busyId === confirmingDelete} onClick={() => confirmDelete(confirmingDelete)}>
            {busyId === confirmingDelete ? 'Deleting…' : 'Delete'}
          </button>{' '}
          <button type="button" disabled={busyId === confirmingDelete} onClick={() => setConfirmingDelete(null)}>
            Cancel
          </button>
        </div>
      )}
    </section>
  )
}
