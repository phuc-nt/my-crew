// Số liệu · engines: which engine eats the budget over the chosen window — cost, share
// of total, calls, failures, tokens, average latency. Costliest first, as the backend
// orders it.
import { useEngineCosts } from '../../api/queries/use-system-queries'
import { EmptyState } from '../../components/ui/empty-state'
import { ProgressBar } from '../../components/ui/progress-bar'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'
import { pct } from './insights-shared'

export function InsightsEnginePanel({ days }: { days: number }) {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useEngineCosts(days)

  return (
    <section className="insights-panel" data-testid="insights-engines">
      <h3>{t('systemInsights.engineTitle')}</h3>
      <p className="muted">{t('systemInsights.engineHint', { days })}</p>
      {isLoading && <p>{t('cost.loading')}</p>}
      {(isError || (!isLoading && !data)) && (
        <p className="error">{t('systemInsights.engineLoadError')}</p>
      )}
      {data && data.engines.length === 0 && <EmptyState>{t('systemInsights.engineEmpty')}</EmptyState>}
      {data && data.engines.length > 0 && (
        <table className="insights-table">
          <thead>
            <tr>
              <th>{t('systemInsights.colEngine')}</th>
              <th className="num">{t('systemInsights.colCost')}</th>
              <th>{t('systemInsights.colShare')}</th>
              <th className="num">{t('systemInsights.colCalls')}</th>
              <th className="num">{t('systemInsights.colFailed')}</th>
              <th className="num">{t('systemInsights.colTokens')}</th>
              <th className="num">{t('systemInsights.colAvgMs')}</th>
            </tr>
          </thead>
          <tbody>
            {data.engines.map((e) => {
              const share = data.total_cost_usd > 0 ? e.cost_usd / data.total_cost_usd : 0
              return (
                <tr key={e.engine}>
                  <td>{e.engine}</td>
                  <td className="num">{formatCost(e.cost_usd)}</td>
                  <td>
                    <span className="insights-share">{pct(share)}</span>
                    <ProgressBar value={share} tone="accent" label={e.engine} />
                  </td>
                  <td className="num">{e.calls}</td>
                  <td className={e.failed > 0 ? 'num warn-text' : 'num'}>{e.failed}</td>
                  <td className="num">{e.input_tokens.toLocaleString()} / {e.output_tokens.toLocaleString()}</td>
                  <td className="num">{e.avg_duration_ms == null ? '—' : Math.round(e.avg_duration_ms)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
