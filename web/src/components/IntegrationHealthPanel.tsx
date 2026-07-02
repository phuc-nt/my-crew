// Integration health panel (top of Team view): green/red dot + label per check from
// GET /api/health/integrations. A failing check shows detail + hint so a non-technical
// operator can see what's broken and what the technical fix is. Manual refresh button —
// the backend caches for 30s so polling is not needed.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { IntegrationCheck } from '../types'

export function IntegrationHealthPanel() {
  const [checks, setChecks] = useState<IntegrationCheck[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getIntegrationHealth()
      .then((res) => setChecks(res.checks))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'health check failed'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section className="health-panel">
      <h3>
        Integration health{' '}
        <button type="button" disabled={loading} onClick={load}>
          {loading ? 'Checking…' : 'Refresh'}
        </button>
      </h3>
      {error && <p className="error">Error: {error}</p>}
      <ul className="health-checks">
        {checks.map((c) => (
          <li key={c.id} className={c.ok ? 'health-ok' : 'health-fail'}>
            <span className={c.ok ? 'health-dot health-dot-ok' : 'health-dot health-dot-fail'} />{' '}
            {c.label}
            {!c.ok && (
              <div className="muted health-detail">
                {c.detail} — {c.hint}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
