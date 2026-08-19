// Cài đặt — the two flags that change how the fleet behaves, plus integration health.
//
// Theme and language are NOT here: they live in the shell header, and a second control
// for one setting is a bug waiting to happen. The old view's "Nâng cao" link list is gone
// too — every route it pointed at is now a tab on the team or system hub.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { useCompany } from '../../api/queries/use-system-queries'
import { queryKeys } from '../../api/queries/query-keys'
import { IntegrationHealthPanel } from '../../components/IntegrationHealthPanel'
import { useLanguage } from '../../i18n/language-context'
import { useUiMode } from '../../ui-mode-context'

export function SettingsTab() {
  const { t } = useLanguage()
  const { isHigh, setMode } = useUiMode()
  const qc = useQueryClient()
  const { data: company } = useCompany()
  const [saveError, setSaveError] = useState<string | null>(null)

  // Flip ONLY the auto-confirm flag — name/coordinator/cap are re-sent unchanged and the
  // backend preserves the rest of company.yaml via load-modify-save.
  const toggleAutoConfirm = (on: boolean) => {
    if (!company) return
    setSaveError(null)
    api
      .saveCompany(company.name, company.coordinator_id, company.team_task_cap_usd, on)
      .then(() => qc.invalidateQueries({ queryKey: queryKeys.team.company() }))
      .catch((e: unknown) => setSaveError(e instanceof Error ? e.message : t('settings.saveFailed')))
  }

  return (
    <div className="settings-page">
      <section className="mode-toggle-box">
        <h3>{t('settings.assignSectionTitle')}</h3>
        <label className="mode-toggle">
          <input
            type="checkbox"
            checked={company?.team_task_auto_confirm ?? false}
            disabled={!company}
            onChange={(e) => toggleAutoConfirm(e.target.checked)}
          />{' '}
          {t('settings.autoConfirmLabel')}
        </label>
        <p className="muted">{t('settings.autoConfirmHint')}</p>
        {saveError && <p className="error">{t('settings.errorPrefix', { message: saveError })}</p>}
      </section>

      <section className="mode-toggle-box">
        <h3>{t('settings.displayModeTitle')}</h3>
        <label className="mode-toggle">
          <input
            type="checkbox"
            checked={isHigh}
            onChange={(e) => setMode(e.target.checked ? 'high' : 'low')}
          />{' '}
          {t('settings.advancedModeLabel')}
        </label>
        <p className="muted">{t('settings.advancedModeHint')}</p>
      </section>

      <IntegrationHealthPanel />
    </div>
  )
}
