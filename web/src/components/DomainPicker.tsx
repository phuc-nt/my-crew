// Step 1 of the create-agent wizard: loads GET /api/packs and renders a radio list of
// installed domain packs (name + the report kinds each pack serves). Selecting a pack is
// the input the rest of the wizard (reports/bindings) filters against.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Pack } from '../types'

export function DomainPicker({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (pack: Pack) => void
}) {
  const [packs, setPacks] = useState<Pack[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getPacks()
      .then((res) => setPacks(res.packs))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'failed to load packs'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p>Loading domain packs…</p>
  if (error) return <p className="error">Error: {error}</p>
  if (packs.length === 0) return <p className="muted">No domain packs installed.</p>

  return (
    <fieldset className="domain-picker">
      <legend>Choose a domain pack</legend>
      {packs.map((p) => (
        <label key={p.id} className="domain-picker-option">
          <input
            type="radio"
            name="domain"
            value={p.id}
            checked={selected === p.id}
            onChange={() => onSelect(p)}
          />{' '}
          <strong>{p.name}</strong> <span className="muted">({p.id})</span>
          <div className="muted">reports: {p.report_kinds.join(', ') || 'none'}</div>
        </label>
      ))}
    </fieldset>
  )
}
