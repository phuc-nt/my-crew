// /team — the roster hub. Everything the CEO does to the team itself lives here: see who
// exists, pause/resume/run/remove them, and add new ones. Creating is an inline panel
// rather than a separate route, which is what makes "template → agent" fit in three
// clicks (open panel → Tạo ngay → xác nhận) instead of a multi-page wizard.
import { Suspense, lazy, useState } from 'react'
import { Link } from 'react-router'
import { useCompany, useTeamAlerts } from '../../api/queries/use-team-queries'
import { IntegrationHealthPanel } from '../../components/IntegrationHealthPanel'
import { Button } from '../../components/ui/button'
import { PageHeader } from '../../components/ui/page-header'
import { useLanguage } from '../../i18n/language-context'
import { CoordinatorHealthBanner } from '../shared/coordinator-health-banner'

import { OrphanList } from './orphan-list'
import { RosterTable } from './roster-table'

const HirePanel = lazy(() => import('./create/hire-panel'))

export function TeamPage() {
  const { t } = useLanguage()
  const { data: company } = useCompany()
  const { data: alertsPayload } = useTeamAlerts()
  const [createOpen, setCreateOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const alerts = alertsPayload?.alerts ?? []

  return (
    <section data-testid="team-page">
      <IntegrationHealthPanel />
      {/* After a crew is created the team does nothing until the coordinator daemon runs;
          this banner is the only place that gap is visible instead of silent. */}
      <CoordinatorHealthBanner />

      <PageHeader
        title={company?.name ?? t('team.title')}
        actions={
          <div className="team-actions">
            <Button variant="ghost" onClick={() => setCreateOpen((v) => !v)}>
              {createOpen ? t('team.hireClose') : t('team.hireOpen')}
            </Button>
            <Link to="/system?tab=company" className="btn-link">
              {t('team.docsRepo')}
            </Link>
          </div>
        }
      />
      {company && (
        <p className="muted team-company-line">
          {company.coordinator_id
            ? t('team.companyCoordinator', { id: company.coordinator_id })
            : t('team.companyNoCoordinator')}
        </p>
      )}

      {alerts.length > 0 && (
        <div className="team-alerts" role="alert">
          {alerts.map((al, i) => (
            <p key={i} className={al.severity === 'high' ? 'error' : 'muted'}>
              {al.severity === 'high' ? '🔴' : '🟡'} <strong>{al.agent_id}</strong>: {al.message}
            </p>
          ))}
        </div>
      )}

      {createOpen && (
        <section className="team-hire" data-testid="team-hire">
          <Suspense fallback={<p>{t('agentPage.loading')}</p>}>
            <HirePanel />
          </Suspense>
        </section>
      )}

      {error && <p className="error">{t('team.errorPrefix', { message: error })}</p>}
      {note && (
        <p className="ok" role="status">
          {note}{' '}
          <Button variant="ghost" onClick={() => setNote(null)}>
            {t('team.upgradeNoteClose')}
          </Button>
        </p>
      )}

      <RosterTable onError={setError} onNote={setNote} />
      <OrphanList onError={setError} />
    </section>
  )
}
