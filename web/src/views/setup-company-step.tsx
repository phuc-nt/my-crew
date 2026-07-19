// Setup wizard's company step: name + optional coordinator select, written via
// POST /api/company. Split out of Setup.tsx to keep that file under the project's
// modularization guideline — this is pure presentation, all state/fetch stays in Setup.tsx.
import { Button } from '../components/ui/button'
import { useLanguage } from '../i18n/language-context'
import type { AgentSummary } from '../types'

export function SetupCompanyStep({
  companyName,
  setCompanyName,
  coordinatorId,
  setCoordinatorId,
  agents,
  busy,
  error,
  onBack,
  onNext,
}: {
  companyName: string
  setCompanyName: (v: string) => void
  coordinatorId: string
  setCoordinatorId: (v: string) => void
  agents: AgentSummary[]
  busy: boolean
  error: string | null
  onBack: () => void
  onNext: () => void
}) {
  const { t } = useLanguage()
  return (
    <>
      <h1>{t('setupCompany.title')}</h1>
      <p className="setup-hint">{t('setupCompany.hint')}</p>
      <label>
        {t('setupCompany.nameLabel')}
        <input
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          placeholder={t('setupCompany.namePlaceholder')}
        />
      </label>
      <label>
        {t('setupCompany.coordinatorLabel')}
        <select value={coordinatorId} onChange={(e) => setCoordinatorId(e.target.value)}>
          <option value="">{t('setupCompany.coordinatorNone')}</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.id})
            </option>
          ))}
        </select>
      </label>
      {error && <p className="error">{error}</p>}
      <div className="setup-actions">
        <Button variant="ghost" disabled={busy} onClick={onBack}>
          {t('setupCompany.back')}
        </Button>
        <Button variant="primary" className="setup-primary-align" disabled={busy} onClick={onNext}>
          {t('setupCompany.continue')}
        </Button>
      </div>
    </>
  )
}
