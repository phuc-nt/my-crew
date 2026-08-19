// The work hub: everything the fleet is doing, or waiting on the CEO to decide.
//
// Four tabs over one page rather than four routes, because they answer one question
// ("what is happening with the work?") from four angles. The tab lives in the URL so a
// specific view — the schedule, say — is linkable and survives a reload.
import { useSearchParams } from 'react-router'
import { ApprovalsQueue, usePendingCount } from '../../components/approvals-queue'
import { AutoApprovedPanel } from './auto-approved-panel'
import { PageHeader } from '../../components/ui/page-header'
import type { UiKey } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'
import { CompanyActivity } from '../../views/CompanyActivity'
import { BoardView } from './board/board-view'
import { OutputsView } from './outputs-view'
import { ScheduleView } from './schedule-view'

const TABS: { id: string; labelKey: UiKey }[] = [
  { id: 'board', labelKey: 'workHub.tabBoard' },
  { id: 'outputs', labelKey: 'workHub.tabOutputs' },
  { id: 'schedule', labelKey: 'workHub.tabSchedule' },
  { id: 'activity', labelKey: 'workHub.tabActivity' },
]

export function WorkPage() {
  const { t } = useLanguage()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab = TABS.some((x) => x.id === requested) ? (requested as string) : 'board'
  const pending = usePendingCount()

  return (
    <section className="work-page" data-testid="work-page">
      <PageHeader title={t('work.title')} />

      {/* The queue sits above the tabs, not inside one: it is the only part of this page
          that is BLOCKING, so it must be visible whichever angle the CEO came here for. */}
      <section className="work-approvals">
        <h3>
          {t('work.pendingApprovalTitle')}{' '}
          {pending > 0 && <span className="badge">{pending}</span>}
        </h3>
        <ApprovalsQueue />
      </section>
      <AutoApprovedPanel />

      <nav className="agent-tabs" aria-label={t('workHub.tabsLabel')}>
        {TABS.map((x) => (
          <button
            key={x.id}
            type="button"
            className={x.id === tab ? 'tab-active' : undefined}
            onClick={() => setParams({ tab: x.id }, { replace: true })}
          >
            {t(x.labelKey)}
          </button>
        ))}
      </nav>

      {tab === 'board' && <BoardView />}
      {tab === 'outputs' && <OutputsView />}
      {tab === 'schedule' && <ScheduleView />}
      {tab === 'activity' && <CompanyActivity />}
    </section>
  )
}
