// Số liệu · budget: the fleet-wide spend as a hero tile with a status badge and a
// utilisation bar, then the per-agent table. The backend only serves cost per agent, and
// the agent's own page already has that breakdown — so every row links there instead of
// rebuilding a second agent selector here.
import { Link } from 'react-router'
import { useFleetBudget } from '../../api/queries/use-system-queries'
import { Badge } from '../../components/ui/badge'
import { EmptyState } from '../../components/ui/empty-state'
import { ProgressBar } from '../../components/ui/progress-bar'
import { StatTile } from '../../components/ui/stat-tile'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'
import { pct, ratioTone } from './insights-shared'

const STATUS_KEY = {
  ok: 'systemInsights.statusOk',
  warn: 'systemInsights.statusWarn',
  danger: 'systemInsights.statusOver',
} as const

export function InsightsBudgetPanel() {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useFleetBudget()

  if (isLoading) return <p>{t('cost.loading')}</p>
  if (isError || !data) return <p className="error">{t('systemInsights.loadError')}</p>

  const tone = ratioTone(data.ratio)
  const overCap = data.agents.filter((a) => a.ratio >= 1).length

  return (
    <section className="insights-panel" data-testid="insights-budget">
      <h3>{t('systemInsights.budgetTitle')}</h3>
      <p className="muted">{t('systemInsights.budgetHint')}</p>
      <div className="stat-grid">
        <StatTile
          label={t('systemInsights.tileSpent')}
          value={formatCost(data.total_spent_usd)}
          badge={<Badge tone={tone} data-testid="budget-status">{t(STATUS_KEY[tone])}</Badge>}
          footer={
            <>
              <ProgressBar value={data.ratio} tone={tone} label={t('systemInsights.ratioBarLabel')} />
              {t('systemInsights.total', {
                spent: formatCost(data.total_spent_usd),
                cap: formatCost(data.total_cap_usd),
                pct: (data.ratio * 100).toFixed(0),
              })}
            </>
          }
        />
        <StatTile label={t('systemInsights.tileCap')} value={formatCost(data.total_cap_usd)} />
        <StatTile label={t('systemInsights.tileAgents')} value={data.agents.length} />
        <StatTile
          label={t('systemInsights.tileOver')}
          value={overCap}
          badge={overCap > 0 ? <Badge tone="danger">{t('systemInsights.statusOver')}</Badge> : undefined}
        />
      </div>
      {data.agents.length === 0 ? (
        <EmptyState>{t('systemInsights.empty')}</EmptyState>
      ) : (
        <table className="budget-table insights-table">
          <thead>
            <tr>
              <th>{t('systemInsights.colAgent')}</th>
              <th className="num">{t('systemInsights.colSpent')}</th>
              <th className="num">{t('systemInsights.colCap')}</th>
              <th>{t('systemInsights.colRatio')}</th>
            </tr>
          </thead>
          <tbody>
            {data.agents.map((a) => (
              <tr key={a.agent_id}>
                <td>
                  <Link to={`/team/${encodeURIComponent(a.agent_id)}?tab=budget`}>{a.agent_id}</Link>
                </td>
                <td className="num">{formatCost(a.spent_usd)}</td>
                <td className="num">{formatCost(a.cap_usd)}</td>
                {/* Over-cap is the only state worth colouring the number: it stops work. */}
                <td className={a.ratio >= 1 ? 'error' : undefined}>
                  <span className="insights-share">{pct(a.ratio)}</span>
                  <ProgressBar value={a.ratio} tone={ratioTone(a.ratio)} label={a.agent_id} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
