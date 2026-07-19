// Memory & Automation view: remembered facts (internal-only) + pending proposals. Both
// READ-only here — the approve/reject actions are the S4 ops surface. Two fetches via the
// shared hook (memory is internal-only by the API's audience gate; default audience=internal).
import { FactsList } from '../components/FactsList'
import { PendingProposals } from '../components/PendingProposals'
import { api } from '../api/client'
import { PageHeader } from '../components/ui/page-header'
import { useAgentData } from '../hooks/use-agent-data'
import { useLanguage } from '../i18n/language-context'
import type { AutomationPayload, MemoryPayload } from '../types'

export function MemoryAutomation() {
  const { t } = useLanguage()
  const mem = useAgentData<MemoryPayload>(api.getMemory)
  const auto = useAgentData<AutomationPayload>(api.getAutomation)

  return (
    <section>
      <PageHeader title={t('memoryAuto.title')} />

      <h3>{t('memoryAuto.rememberedTitle')}</h3>
      {mem.loading ? (
        <p>{t('memoryAuto.loading')}</p>
      ) : mem.error ? (
        <p className="error">{t('memoryAuto.errorPrefix', { message: mem.error })}</p>
      ) : (
        <FactsList facts={mem.data?.facts ?? []} />
      )}

      <h3>{t('memoryAuto.proposalsTitle')}</h3>
      {auto.loading ? (
        <p>{t('memoryAuto.loading')}</p>
      ) : auto.error ? (
        <p className="error">{t('memoryAuto.errorPrefix', { message: auto.error })}</p>
      ) : (
        <PendingProposals pending={auto.data?.pending ?? []} />
      )}
    </section>
  )
}
