// Hub Hệ thống — the fifth hub: everything that configures the fleet rather than doing
// its work. Five tabs, each absorbing a former top-level route.
//
// Tab state rides in the URL like the other hubs, so "the connections screen" is still a
// link someone can send.
import { useSearchParams } from 'react-router'
import { PageHeader } from '../../components/ui/page-header'
import { useLanguage } from '../../i18n/language-context'
import type { UiKey } from '../../i18n/dictionary'
import { AuditTab } from './audit-tab'
import { CompanyTab } from './company-tab'
import { ConnectionsTab } from './connections-tab'
import { InsightsTab } from './insights-tab'
import { SettingsTab } from './settings-tab'

const TABS: { id: string; labelKey: UiKey }[] = [
  { id: 'settings', labelKey: 'systemHub.tabSettings' },
  { id: 'connections', labelKey: 'systemHub.tabConnections' },
  { id: 'company', labelKey: 'systemHub.tabCompany' },
  { id: 'insights', labelKey: 'systemHub.tabInsights' },
  { id: 'audit', labelKey: 'systemHub.tabAudit' },
]

export function SystemPage() {
  const { t } = useLanguage()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab = TABS.some((x) => x.id === requested) ? (requested as string) : 'settings'

  const select = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('tab', id)
    // Switching tabs drops a filter that only made sense on the tab being left.
    if (id !== 'audit') next.delete('task_id')
    setParams(next)
  }

  return (
    <section className="system-page" data-testid="system-page">
      <PageHeader title={t('systemHub.title')} />
      <nav className="agent-tabs" aria-label={t('systemHub.tabsLabel')}>
        {TABS.map((x) => (
          <button
            key={x.id}
            type="button"
            className={tab === x.id ? 'tab-active' : undefined}
            onClick={() => select(x.id)}
          >
            {t(x.labelKey)}
          </button>
        ))}
      </nav>
      {tab === 'settings' && <SettingsTab />}
      {tab === 'connections' && <ConnectionsTab />}
      {tab === 'company' && <CompanyTab />}
      {tab === 'insights' && <InsightsTab />}
      {tab === 'audit' && <AuditTab />}
    </section>
  )
}
