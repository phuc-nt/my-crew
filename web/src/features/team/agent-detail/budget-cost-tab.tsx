// Ngân sách & chi phí — the old /cost and /guardrail in one place. They were separate
// routes but answer one question together: what has this agent spent, and what did the
// gateway let it do to spend it.
import { useAudit, useCost } from '../../../api/queries/use-agent-detail-queries'
import { AuditTable } from '../../../components/AuditTable'
import { LazyCostChart, LazyVerdictChart } from '../../../components/charts/lazy-charts'
import { EmptyState } from '../../../components/ui/empty-state'
import { useLanguage } from '../../../i18n/language-context'
import { formatCost } from '../../../labels'
import { useTheme } from '../../../theme-context'

export function BudgetCostTab({ id }: { id: string }) {
  const { t } = useLanguage()
  // Remount the charts when the RESOLVED theme flips so Chart.js re-reads token colors.
  const { resolved } = useTheme()
  const { data: cost, isLoading: costLoading } = useCost(id)
  const { data: audit } = useAudit(id)

  const ratio = cost && cost.cap > 0 ? cost.spent_this_month / cost.cap : 0
  const verdicts = audit ? Object.values(audit.counts).reduce((a, b) => a + b, 0) : 0

  return (
    <div>
      <h4>{t('cost.title')}</h4>
      {costLoading || !cost ? (
        <p>{t('cost.loading')}</p>
      ) : (
        <>
          <p>
            {t('cost.thisMonthPrefix')}
            <strong>{formatCost(cost.spent_this_month)}</strong>
            {t('cost.capSuffix')}
            {formatCost(cost.cap)} ({(ratio * 100).toFixed(0)}%
            {ratio >= cost.warn_ratio ? ' ⚠️' : ''})
          </p>
          {cost.series.length === 0 ? (
            <EmptyState>{t('cost.empty')}</EmptyState>
          ) : (
            <LazyCostChart key={resolved} series={cost.series} cap={cost.cap} />
          )}
        </>
      )}

      <h4>{t('guardrail.title')}</h4>
      <p>{t('guardrail.totalDecisions', { n: verdicts })}</p>
      {audit && verdicts > 0 && (
        <div className="chart-box">
          <LazyVerdictChart key={resolved} counts={audit.counts} />
        </div>
      )}
      <h5>{t('guardrail.recentTitle')}</h5>
      <AuditTable rows={audit?.recent ?? []} />
    </div>
  )
}
