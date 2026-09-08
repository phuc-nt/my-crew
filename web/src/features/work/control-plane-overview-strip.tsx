// The work hub's headline row: how deep the queue is, what is running, what is stuck,
// how many decisions wait — plus whether the coordinator that moves all of it is alive.
//
// Reads the same `/api/control-plane/overview` an outside script would, so the numbers
// the CEO sees here are the numbers a monitor would get; nothing is recomputed client-side.
import { useControlPlaneOverview } from '../../api/queries/use-control-plane-queries'
import { Badge } from '../../components/ui/badge'
import { StatTile } from '../../components/ui/stat-tile'
import { useLanguage } from '../../i18n/language-context'

export function ControlPlaneOverviewStrip() {
  const { t } = useLanguage()
  const { data, isError } = useControlPlaneOverview()

  if (isError) {
    return (
      <p className="muted control-plane-strip-error" data-testid="control-plane-strip">
        {t('controlPlane.loadFailed')}
      </p>
    )
  }
  if (!data) return null

  const { queue, approvals, health } = data
  const byAgent = Object.entries(approvals.pending_by_agent)
  return (
    <section className="control-plane-strip" data-testid="control-plane-strip">
      <div className="control-plane-strip-head">
        <h3>{t('controlPlane.title')}</h3>
        <Badge tone={health.coordinator_ok ? 'ok' : 'danger'} className="control-plane-coordinator">
          {health.coordinator_ok ? t('controlPlane.coordinatorOk') : t('controlPlane.coordinatorDown')}
        </Badge>
      </div>
      <div className="stat-grid">
        <StatTile label={t('controlPlane.queueDepth')} value={queue.depth} />
        <StatTile label={t('controlPlane.running')} value={queue.running} />
        <StatTile
          label={t('controlPlane.stalled')}
          value={queue.stalled}
          className={queue.stalled > 0 ? 'stat-tile-warn' : undefined}
          badge={queue.stalled > 0 ? <Badge tone="warn">!</Badge> : undefined}
        />
        <StatTile
          label={t('controlPlane.pendingApprovals')}
          value={approvals.pending_total}
          footer={
            byAgent.length > 0
              ? byAgent.map(([agent, n]) => `${agent} ×${n}`).join(' · ')
              : undefined
          }
        />
      </div>
    </section>
  )
}
