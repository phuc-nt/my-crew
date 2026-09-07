// Số liệu — the fleet dashboard: budget, spend per engine, routing retro, tool health.
//
// One toolbar rules all four panels: the day window rides in the URL (`?days=`) so a
// "last 30 days" view is a link, a Refresh button refetches every panel at once, and an
// "updated Ns ago" line says how stale the numbers are. Each panel owns its own query so
// one slow aggregate never blanks the others.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { queryKeys } from '../../api/queries/query-keys'
import { useFleetBudget } from '../../api/queries/use-system-queries'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import { InsightsBudgetPanel } from './insights-budget-panel'
import { InsightsEnginePanel } from './insights-engine-panel'
import { InsightsRoutingPanel } from './insights-routing-panel'
import { DAY_CHOICES, DEFAULT_DAYS, parseDays } from './insights-shared'
import { InsightsToolPanel } from './insights-tool-panel'

export function InsightsTab() {
  const { t } = useLanguage()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const days = parseDays(params.get('days'))
  // The budget query is the tab's clock: its last fetch time drives "updated Ns ago".
  const { dataUpdatedAt, isFetching } = useFleetBudget()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 10_000)
    return () => clearInterval(id)
  }, [])

  const setDays = (n: number) => {
    const next = new URLSearchParams(params)
    if (n === DEFAULT_DAYS) next.delete('days')
    else next.set('days', String(n))
    setParams(next)
  }

  const refresh = () => {
    setNow(Date.now())
    void Promise.all([
      qc.invalidateQueries({ queryKey: queryKeys.system.budget() }),
      qc.invalidateQueries({ queryKey: queryKeys.system.routeStats() }),
      qc.invalidateQueries({ queryKey: queryKeys.system.toolStats(days) }),
      qc.invalidateQueries({ queryKey: queryKeys.system.engineCosts(days) }),
    ])
  }

  const agoS = dataUpdatedAt > 0 ? Math.max(0, Math.round((now - dataUpdatedAt) / 1000)) : null

  return (
    <div className="system-insights">
      <div className="insights-toolbar" role="toolbar" aria-label={t('systemInsights.toolbarLabel')}>
        <div className="insights-days" role="group" aria-label={t('systemInsights.windowLabel')}>
          {DAY_CHOICES.map((n) => (
            <Button
              key={n}
              variant="chip"
              className={n === days ? 'chip-active' : undefined}
              aria-pressed={n === days}
              onClick={() => setDays(n)}
            >
              {t('systemInsights.daysN', { n })}
            </Button>
          ))}
        </div>
        <span className="spacer" />
        {agoS != null && (
          <span className="muted" aria-live="polite" data-testid="insights-updated">
            {isFetching ? t('cost.loading') : t('systemInsights.updatedAgo', { s: agoS })}
          </span>
        )}
        <Button onClick={refresh} disabled={isFetching}>{t('systemInsights.refresh')}</Button>
      </div>
      <InsightsBudgetPanel />
      <InsightsEnginePanel days={days} />
      <InsightsRoutingPanel />
      <InsightsToolPanel days={days} />
    </div>
  )
}
