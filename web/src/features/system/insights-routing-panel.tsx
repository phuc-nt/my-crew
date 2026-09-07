// Số liệu · routing: the retro the chat command `route stats` prints, as tiles and
// ranked lists — which way tasks were run, who decided, and how sprints that ran out
// ended. Labels come from the backend so the web and chat name things identically.
import { useRouteStats } from '../../api/queries/use-system-queries'
import { EmptyState } from '../../components/ui/empty-state'
import { ProgressBar } from '../../components/ui/progress-bar'
import { StatTile } from '../../components/ui/stat-tile'
import { useLanguage } from '../../i18n/language-context'
import type { RankedCount } from '../../types'

function RankedList({ title, items, total, extra }: {
  title: string
  items: RankedCount[]
  total: number
  extra?: (item: RankedCount) => string | null
}) {
  if (items.length === 0) return null
  return (
    <div>
      <h4>{title}</h4>
      <ul className="ranked-list">
        {items.map((it) => (
          <li key={it.id}>
            <span>{it.label}</span>
            <ProgressBar value={total > 0 ? it.count / total : 0} tone="accent" label={it.label} />
            <span className="ranked-count">
              {extra?.(it) ? `${it.count} · ${extra(it)}` : it.count}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function InsightsRoutingPanel() {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useRouteStats()

  return (
    <section className="insights-panel" data-testid="insights-routing">
      <h3>{t('systemInsights.routingTitle')}</h3>
      <p className="muted">{t('systemInsights.routingHint')}</p>
      {isLoading && <p>{t('cost.loading')}</p>}
      {(isError || (!isLoading && !data)) && (
        <p className="error">{t('systemInsights.routingLoadError')}</p>
      )}
      {data && data.total === 0 && <EmptyState>{t('systemInsights.routingEmpty')}</EmptyState>}
      {data && data.total > 0 && (
        <>
          <div className="stat-grid">
            <StatTile label={t('systemInsights.tileRouted')} value={data.total} />
            <StatTile label={t('systemInsights.tileDeadEnds')} value={data.dead_ends} />
            <StatTile label={t('systemInsights.tileDowngrades')} value={data.downgrades} />
            <StatTile label={t('systemInsights.tileFailed')} value={data.failed} />
          </div>
          <div className="insights-columns">
            <RankedList title={t('systemInsights.byMode')} items={data.by_mode} total={data.total} />
            <RankedList title={t('systemInsights.bySource')} items={data.by_source} total={data.total} />
            <RankedList title={t('systemInsights.byShape')} items={data.by_shape} total={data.total} />
            <RankedList
              title={t('systemInsights.byEffort')}
              items={data.by_effort}
              total={data.total}
              extra={(it) => {
                const row = data.by_effort.find((e) => e.id === it.id)
                return row && row.dead_ends > 0 ? t('systemInsights.deadEndsOf', { n: row.dead_ends }) : null
              }}
            />
            <RankedList
              title={t('systemInsights.byFailure')}
              items={data.by_failure}
              total={data.failed}
              extra={(it) => data.by_failure.find((f) => f.id === it.id)?.group_label ?? null}
            />
          </div>
        </>
      )}
    </section>
  )
}
