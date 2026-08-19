// Trí nhớ — the old /memory view. Facts and proposals load independently on purpose: one
// failing must not blank the other, since they come from different subsystems.
import { useAutomation, useMemory } from '../../../api/queries/use-agent-detail-queries'
import { FactsList } from '../../../components/FactsList'
import { PendingProposals } from '../../../components/PendingProposals'
import { useLanguage } from '../../../i18n/language-context'

export function MemoryTab({ id }: { id: string }) {
  const { t } = useLanguage()
  const mem = useMemory(id)
  const auto = useAutomation(id)

  return (
    <div>
      <h4>{t('memoryAuto.rememberedTitle')}</h4>
      {mem.isLoading ? (
        <p>{t('memoryAuto.loading')}</p>
      ) : mem.isError ? (
        <p className="error">{t('memoryAuto.errorPrefix', { message: '' })}</p>
      ) : (
        <FactsList facts={mem.data?.facts ?? []} />
      )}

      <h4>{t('memoryAuto.proposalsTitle')}</h4>
      {auto.isLoading ? (
        <p>{t('memoryAuto.loading')}</p>
      ) : auto.isError ? (
        <p className="error">{t('memoryAuto.errorPrefix', { message: '' })}</p>
      ) : (
        <PendingProposals pending={auto.data?.pending ?? []} />
      )}
    </div>
  )
}
