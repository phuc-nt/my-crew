// Dual-lens P2 (high-mode only — parent gates it): one always-on status line above the
// office canvas — coordinator heartbeat + the same integration checks the Connections
// page shows, compressed to ✓/✗ chips. Poll cadence matches the server's 30s cache on
// /api/health/integrations, so polling faster would only re-read the cache. The red
// CoordinatorHealthBanner stays the loud low-mode surface for a DEAD coordinator; this
// strip is the maintainer's steady-state readout, not a replacement.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { CoordinatorHealthPayload, IntegrationCheck } from '../../types'

const POLL_MS = 30_000

export function OfficeHealthStrip() {
  const [beat, setBeat] = useState<CoordinatorHealthPayload | null>(null)
  const [checks, setChecks] = useState<IntegrationCheck[]>([])

  useEffect(() => {
    let stop = false
    const poll = () => {
      api.getCoordinatorHealth().then((h) => { if (!stop) setBeat(h) }).catch(() => undefined)
      api.getIntegrationHealth().then((p) => { if (!stop) setChecks(p.checks) }).catch(() => undefined)
    }
    poll()
    const t = setInterval(poll, POLL_MS)
    return () => { stop = true; clearInterval(t) }
  }, [])

  const failing = checks.filter((c) => !c.ok)
  return (
    <div className="office-health-strip" aria-label="Sức khỏe hệ thống">
      <span className={beat?.alive ? 'health-chip health-ok' : 'health-chip health-bad'}>
        {beat?.alive
          ? `♥ điều phối ${Math.round(beat.last_beat_ago_s ?? 0)}s`
          : '♥ điều phối: mất nhịp'}
      </span>
      <span className="health-chip health-ok">✓ {checks.length - failing.length}</span>
      {failing.map((c) => (
        <span key={c.id} className="health-chip health-bad" title={`${c.detail} — ${c.hint}`}>
          ✗ {c.label}
        </span>
      ))}
    </div>
  )
}
