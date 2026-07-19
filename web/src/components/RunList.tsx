// Run history list (newest-first, allowlisted run-events from /api/runs). Status-styled.
import { useLanguage } from '../i18n/language-context'
import { AUDIENCE_LABEL, KIND_LABEL, RUN_STATUS_LABEL, formatCost, formatDateTime, labelFor } from '../labels'
import type { RunEvent } from '../types'

export function RunList({ runs }: { runs: RunEvent[] }) {
  const { t } = useLanguage()
  if (runs.length === 0) return <p>{t('runList.empty')}</p>
  return (
    <div className="table-scroll">
    <table className="runs-table">
      <thead>
        <tr>
          <th>{t('runList.colTime')}</th>
          <th>{t('runList.colKind')}</th>
          <th>{t('runList.colAudience')}</th>
          <th>{t('runList.colStatus')}</th>
          <th>{t('runList.colCost')}</th>
          <th>{t('runList.colDelivered')}</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r, i) => (
          <tr key={`${r.ts}-${i}`}>
            <td>{formatDateTime(r.ts) || r.ts}</td>
            <td>{labelFor(KIND_LABEL, r.kind, t)}</td>
            <td>{labelFor(AUDIENCE_LABEL, r.audience, t)}</td>
            <td className={`status status-${r.status}`}>{labelFor(RUN_STATUS_LABEL, r.status, t)}</td>
            <td>{formatCost(r.cost_usd)}</td>
            <td>{r.delivered ? '✓' : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
