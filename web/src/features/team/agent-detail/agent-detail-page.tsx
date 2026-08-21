// /team/:id — one agent, eight tabs. This page absorbs seven former top-level routes that
// each showed ONE aspect of an agent selected from a global picker; the agent now comes
// from the URL, so the picker is gone and every tab is deep-linkable via ?tab=.
import { Link, useParams, useSearchParams } from 'react-router'
import { useAgentStatus } from '../../../api/queries/use-team-queries'
import { Badge } from '../../../components/ui/badge'
import { useLanguage } from '../../../i18n/language-context'
import type { UiKey } from '../../../i18n/dictionary'
import { RunNowButton } from '../run-now-button'
import { ActivityTab } from './activity-tab'
import { AdvancedTab } from './advanced-tab'
import { BandControl } from './band-control'
import { BudgetCostTab } from './budget-cost-tab'
import { ChannelsTab } from './channels-tab'
import { KnowledgeTab } from './knowledge-tab'
import { MemoryTab } from './memory-tab'
import { ProfileTab } from './profile-tab'
import { SkillsTab } from './skills-tab'

const TABS: { id: string; labelKey: UiKey }[] = [
  { id: 'profile', labelKey: 'agentDetail.tabProfile' },
  { id: 'activity', labelKey: 'agentDetail.tabActivity' },
  { id: 'knowledge', labelKey: 'agentDetail.tabKnowledge' },
  { id: 'skills', labelKey: 'agentDetail.tabSkills' },
  { id: 'channels', labelKey: 'agentDetail.tabChannels' },
  { id: 'budget', labelKey: 'agentDetail.tabBudget' },
  { id: 'memory', labelKey: 'agentDetail.tabMemory' },
  { id: 'advanced', labelKey: 'agentDetail.tabAdvanced' },
]

export function AgentDetailPage() {
  const { t } = useLanguage()
  const { id = '' } = useParams()
  // The tab lives in the URL, not in state: a link to one agent's cost tab has to be
  // sendable, which the old local-state tabs could not do.
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((x) => x.id === params.get('tab')) ? params.get('tab')! : 'profile'
  const { data: status, isLoading, isError } = useAgentStatus(id)

  if (isError)
    return (
      <section>
        <p className="error">{t('agentPage.loadError')}</p>
        <p>
          {t('agentPage.orphanHint')}
          <Link to="/team">{t('agentPage.orphanHintLink')}</Link>
          {t('agentPage.orphanHintSuffix')}
        </p>
      </section>
    )
  if (isLoading || !status) return <p>{t('agentPage.loading')}</p>

  return (
    <section className="agent-page" data-testid="agent-detail-page">
      <header className="agent-page-head">
        <p className="agent-back">
          <Link to="/team">{t('agentPage.back')}</Link>
        </p>
        <h2>
          {status.name} <span className="muted">({id})</span>
        </h2>
        <Badge tone={status.enabled ? 'ok' : 'neutral'}>
          {status.enabled ? t('agentPage.enabled') : t('agentPage.disabled')}
        </Badge>
        {status.trust_mode && (
          <Badge
            tone={status.trust_mode === 'autonomous' ? 'accent' : 'warn'}
            title={
              status.trust_mode === 'autonomous'
                ? t('agentPage.trustAutonomousTitle')
                : t('agentPage.trustGuardedTitle')
            }
          >
            {status.trust_mode === 'autonomous'
              ? t('agentPage.trustAutonomous')
              : t('agentPage.trustGuarded')}
          </Badge>
        )}
        {status.pending_approvals > 0 && (
          <Link to="/work" className="agent-pending">
            {t('agentPage.pendingApprovals', { n: status.pending_approvals })}
          </Link>
        )}
        <BandControl id={id} />
        <RunNowButton agent={{ id, name: status.name, enabled: status.enabled, last_run: status.last_run }} />
      </header>

      <nav className="agent-tabs">
        {TABS.map((x) => (
          <button
            key={x.id}
            type="button"
            className={tab === x.id ? 'tab-active' : undefined}
            onClick={() => setParams({ tab: x.id }, { replace: true })}
          >
            {t(x.labelKey)}
          </button>
        ))}
      </nav>

      {tab === 'profile' && <ProfileTab id={id} status={status} />}
      {tab === 'activity' && <ActivityTab id={id} />}
      {tab === 'knowledge' && <KnowledgeTab id={id} />}
      {tab === 'skills' && <SkillsTab id={id} />}
      {tab === 'channels' && <ChannelsTab id={id} />}
      {tab === 'budget' && <BudgetCostTab id={id} />}
      {tab === 'memory' && <MemoryTab id={id} />}
      {tab === 'advanced' && <AdvancedTab id={id} />}
    </section>
  )
}
