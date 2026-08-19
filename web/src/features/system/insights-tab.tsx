// Số liệu — the fleet-wide budget table.
//
// The backend only serves cost/audit/memory per agent, and phase 4 already put those on
// the agent's own page. So this tab deliberately does NOT rebuild a second agent selector:
// it shows the one number that has no per-agent home — total team spend — and each row
// links to that agent's existing detail tab for the breakdown.
import { Link } from 'react-router'
import { useFleetBudget } from '../../api/queries/use-system-queries'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'

export function InsightsTab() {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useFleetBudget()

  if (isLoading) return <p>{t('cost.loading')}</p>
  if (isError || !data) return <p className="error">{t('systemInsights.loadError')}</p>

  return (
    <div className="system-insights">
      <h3>{t('systemInsights.budgetTitle')}</h3>
      <p className="muted">{t('systemInsights.budgetHint')}</p>
      <p>
        <strong>
          {t('systemInsights.total', {
            spent: formatCost(data.total_spent_usd),
            cap: formatCost(data.total_cap_usd),
            pct: (data.ratio * 100).toFixed(0),
          })}
        </strong>
      </p>
      {data.agents.length === 0 ? (
        <EmptyState>{t('systemInsights.empty')}</EmptyState>
      ) : (
        <table className="budget-table">
          <thead>
            <tr>
              <th>{t('systemInsights.colAgent')}</th>
              <th>{t('systemInsights.colSpent')}</th>
              <th>{t('systemInsights.colCap')}</th>
              <th>{t('systemInsights.colRatio')}</th>
            </tr>
          </thead>
          <tbody>
            {data.agents.map((a) => (
              <tr key={a.agent_id}>
                <td>
                  <Link to={`/team/${encodeURIComponent(a.agent_id)}?tab=budget`}>{a.agent_id}</Link>
                </td>
                <td>{formatCost(a.spent_usd)}</td>
                <td>{formatCost(a.cap_usd)}</td>
                {/* Over-cap is the only state worth colouring: it is the one that stops work. */}
                <td className={a.ratio >= 1 ? 'error' : undefined}>{(a.ratio * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
