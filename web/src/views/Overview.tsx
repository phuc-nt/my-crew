// Overview: the agent list (replaces the htmx index). Renders id/name/enabled + last-run
// status from /api/agents. The first end-to-end proof: FastAPI static → React → /api/agents.
import { useAgent } from '../agent-context'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { KIND_LABEL, RUN_STATUS_LABEL, labelFor } from '../labels'

export function Overview() {
  const { t } = useLanguage()
  const { agents, loading, error } = useAgent()
  if (loading) return <p>{t('overview.loading')}</p>
  if (error) return <p className="error">{t('overview.errorPrefix', { message: error })}</p>
  if (agents.length === 0) return <EmptyState>{t('overview.empty')}</EmptyState>

  return (
    <section>
      <PageHeader title={t('overview.title')} />
      {/* Advanced (technical) view — a distinct class so it does NOT inherit the mobile
          card-list transform meant for the CEO tables; it just scrolls horizontally. */}
      <div className="table-scroll">
        <table className="agents-table-advanced">
          <thead>
            <tr>
              <th>{t('overview.colCode')}</th>
              <th>{t('overview.colName')}</th>
              <th>{t('overview.colEnabled')}</th>
              <th>{t('overview.colLastRun')}</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td>{a.id}</td>
                <td>{a.name}</td>
                <td>{a.enabled ? '✓' : '—'}</td>
                <td>
                  {a.last_run
                    ? `${labelFor(KIND_LABEL, a.last_run.kind, t)} · ${labelFor(RUN_STATUS_LABEL, a.last_run.status, t)}`
                    : t('overview.neverRun')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
