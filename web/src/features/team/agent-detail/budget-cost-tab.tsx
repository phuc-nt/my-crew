// Ngân sách & chi phí — the old /cost and /guardrail in one place. They were separate
// routes but answer one question together: what has this agent spent, and what did the
// gateway let it do to spend it.
// v88 P4: the monthly cap is now editable here (was charts-only, 0 API writes) — patches
// through profile_patch's `budget.monthly_usd` leaf and invalidates the cost query so the
// header/chart cap reflects the new value without a page reload.
import { useState } from 'react'
import {
  useAudit,
  useCost,
  usePatchAgentProfileSettings,
} from '../../../api/queries/use-agent-detail-queries'
import { AuditTable } from '../../../components/AuditTable'
import { Button } from '../../../components/ui/button'
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
  const patchSettings = usePatchAgentProfileSettings(id)
  const [editingCap, setEditingCap] = useState(false)
  const [draftCap, setDraftCap] = useState('')
  const [capError, setCapError] = useState<string | null>(null)

  const ratio = cost && cost.cap > 0 ? cost.spent_this_month / cost.cap : 0
  const verdicts = audit ? Object.values(audit.counts).reduce((a, b) => a + b, 0) : 0

  async function saveCap() {
    setCapError(null)
    const value = Number(draftCap)
    if (!Number.isFinite(value) || value < 0) {
      setCapError(t('cost.capSaveFailed'))
      return
    }
    try {
      await patchSettings.mutateAsync({ budget_monthly_usd: value })
      setEditingCap(false)
    } catch (e) {
      setCapError(e instanceof Error ? e.message : t('cost.capSaveFailed'))
    }
  }

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
          <p>
            <strong>{t('cost.capEditLabel')}:</strong>{' '}
            {editingCap ? (
              <>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={draftCap}
                  onChange={(e) => setDraftCap(e.target.value)}
                />
                <Button variant="primary" disabled={patchSettings.isPending} onClick={() => void saveCap()}>
                  {t('agentDetail.saveBtn')}
                </Button>
                <Button variant="ghost" disabled={patchSettings.isPending} onClick={() => setEditingCap(false)}>
                  {t('agentDetail.cancelBtn')}
                </Button>
                {capError && <span className="error"> {capError}</span>}
              </>
            ) : (
              <>
                {formatCost(cost.cap)}{' '}
                <Button
                  variant="chip"
                  onClick={() => {
                    setDraftCap(String(cost.cap))
                    setCapError(null)
                    setEditingCap(true)
                  }}
                >
                  {t('agentDetail.editBtn')}
                </Button>
              </>
            )}
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
