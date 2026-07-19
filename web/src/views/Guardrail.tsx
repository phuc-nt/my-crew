// Guardrail/Audit view: verdict-breakdown doughnut + recent events table. Shows the
// Action Gateway at work (allow/deny/pending/…). Read-only; consumes /api/audit.
import { AuditTable } from '../components/AuditTable'
import { VerdictChart } from '../components/charts/VerdictChart'
import { api } from '../api/client'
import { PageHeader } from '../components/ui/page-header'
import { useAgentData } from '../hooks/use-agent-data'
import { useLanguage } from '../i18n/language-context'
import { useTheme } from '../theme-context'
import type { AuditPayload } from '../types'

export function Guardrail() {
  const { t } = useLanguage()
  const { data, loading, error } = useAgentData<AuditPayload>(api.getAudit)
  // Remount the chart when the RESOLVED theme flips so it re-reads token colors (v10 M25).
  const { resolved } = useTheme()
  if (loading) return <p>{t('guardrail.loading')}</p>
  if (error) return <p className="error">{t('guardrail.errorPrefix', { message: error })}</p>
  if (!data) return null

  const total = Object.values(data.counts).reduce((a, b) => a + b, 0)
  return (
    <section>
      <PageHeader title={t('guardrail.title')} />
      <p>{t('guardrail.totalDecisions', { n: total })}</p>
      {total > 0 && (
        <div className="chart-box">
          <VerdictChart key={resolved} counts={data.counts} />
        </div>
      )}
      <h3>{t('guardrail.recentTitle')}</h3>
      <AuditTable rows={data.recent} />
    </section>
  )
}
