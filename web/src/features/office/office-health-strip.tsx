// Dual-lens P2 (high-mode only — parent gates it): one always-on status line above the
// office canvas — coordinator heartbeat + the same integration checks the Connections
// page shows, compressed to ✓/✗ chips. Poll cadence matches the server's 30s cache on
// /api/health/integrations, so polling faster would only re-read the cache. The red
// CoordinatorHealthBanner stays the loud low-mode surface for a DEAD coordinator; this
// strip is the maintainer's steady-state readout, not a replacement.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'
import type { CoordinatorHealthPayload, FleetBudgetPayload, IntegrationCheck } from '../../types'

const POLL_MS = 30_000

export function OfficeHealthStrip() {
  const { t } = useLanguage()
  const [beat, setBeat] = useState<CoordinatorHealthPayload | null>(null)
  const [checks, setChecks] = useState<IntegrationCheck[]>([])
  const [budget, setBudget] = useState<FleetBudgetPayload | null>(null)

  useEffect(() => {
    let stop = false
    const poll = () => {
      api.getCoordinatorHealth().then((h) => { if (!stop) setBeat(h) }).catch(() => undefined)
      api.getIntegrationHealth().then((p) => { if (!stop) setChecks(p.checks) }).catch(() => undefined)
      api.getFleetBudget().then((b) => { if (!stop) setBudget(b) }).catch(() => undefined)
    }
    poll()
    const t = setInterval(poll, POLL_MS)
    return () => { stop = true; clearInterval(t) }
  }, [])

  const failing = checks.filter((c) => !c.ok)
  return (
    <div className="office-health-strip" aria-label={t('officeHealthStrip.ariaLabel')}>
      <span className={beat?.alive ? 'health-chip health-ok' : 'health-chip health-bad'}>
        {beat?.alive
          ? t('officeHealthStrip.coordinatorAlive', { seconds: Math.round(beat.last_beat_ago_s ?? 0) })
          : t('officeHealthStrip.coordinatorDead')}
      </span>
      <span className="health-chip health-ok">✓ {checks.length - failing.length}</span>
      {budget && (
        <span
          className={budget.ratio >= 0.8 ? 'health-chip health-bad' : 'health-chip health-ok'}
          title={budget.agents
            .map((a) => `${a.agent_id}: ${formatCost(a.spent_usd)}/${formatCost(a.cap_usd)}`)
            .join(' · ')}
        >
          💰 {formatCost(budget.total_spent_usd)}/{formatCost(budget.total_cap_usd)}
        </span>
      )}
      {failing.map((c) => (
        <span key={c.id} className="health-chip health-bad" title={`${c.detail} — ${c.hint}`}>
          ✗ {c.label}
        </span>
      ))}
    </div>
  )
}
