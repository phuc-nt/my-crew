// Số liệu · tools: per-tool call health pooled over every agent's audit trail for the
// chosen window. Worst failure rate first (the backend's order), denials counted apart
// from body failures, top denial reasons under the row.
import { useToolStats } from '../../api/queries/use-system-queries'
import { Badge } from '../../components/ui/badge'
import { EmptyState } from '../../components/ui/empty-state'
import { ProgressBar } from '../../components/ui/progress-bar'
import { useLanguage } from '../../i18n/language-context'
import { failureTone, pct } from './insights-shared'

export function InsightsToolPanel({ days }: { days: number }) {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useToolStats(days)

  return (
    <section className="insights-panel" data-testid="insights-tools">
      <h3>{t('systemInsights.toolTitle')}</h3>
      <p className="muted">{t('systemInsights.toolHint', { days })}</p>
      {isLoading && <p>{t('cost.loading')}</p>}
      {(isError || (!isLoading && !data)) && (
        <p className="error">{t('systemInsights.toolLoadError')}</p>
      )}
      {data && data.skipped.length > 0 && (
        <p className="muted">{t('systemInsights.toolSkipped', { agents: data.skipped.join(', ') })}</p>
      )}
      {data && data.tools.length === 0 && <EmptyState>{t('systemInsights.toolEmpty')}</EmptyState>}
      {data && data.tools.length > 0 && (
        <table className="insights-table">
          <thead>
            <tr>
              <th>{t('systemInsights.colTool')}</th>
              <th>{t('systemInsights.colFailRate')}</th>
              <th className="num">{t('systemInsights.colTotal')}</th>
              <th className="num">{t('systemInsights.colOk')}</th>
              <th className="num">{t('systemInsights.colFail')}</th>
              <th className="num">{t('systemInsights.colDenied')}</th>
              <th className="num">{t('systemInsights.colAvgMs')}</th>
            </tr>
          </thead>
          <tbody>
            {data.tools.map((row) => {
              const tone = failureTone(row.failure_rate)
              return (
                <tr key={row.tool}>
                  <td>
                    <code>{row.tool}</code>
                    {row.common_errors.length > 0 && (
                      <div className="muted">
                        {row.common_errors.map((e) => `${e.count}× ${e.reason}`).join(' · ')}
                      </div>
                    )}
                  </td>
                  <td>
                    <Badge tone={tone}>{pct(row.failure_rate)}</Badge>
                    <ProgressBar value={row.failure_rate} tone={tone} label={row.tool} />
                  </td>
                  <td className="num">{row.total_calls}</td>
                  <td className="num">{row.successes}</td>
                  <td className="num">{row.failures}</td>
                  <td className="num">{row.denied}</td>
                  <td className="num">{Math.round(row.avg_duration_ms)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
