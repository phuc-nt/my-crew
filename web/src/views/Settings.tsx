// v7 M20: "Cài đặt" — integration health at a glance + a "Nâng cao" section linking the
// technical views the CEO rarely needs (they keep their original components, just moved out
// of the top nav so the daily surface stays 4 items). v10 M26: the health list reuses the
// shared IntegrationHealthPanel (one implementation, DRY) instead of an inline copy.
// v15: adds the team-task auto-confirm toggle (company.yaml flag, config-only write).
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import { IntegrationHealthPanel } from '../components/IntegrationHealthPanel'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { useUiMode } from '../ui-mode-context'
import type { UiKey } from '../i18n/dictionary'
import type { CompanyPayload } from '../types'

// Technical / power-user views — moved here from the flat nav. Nothing is removed; each
// route still renders its existing component.
const ADVANCED: { to: string; labelKey: UiKey }[] = [
  { to: '/overview', labelKey: 'settings.advanced.overview' },
  { to: '/company-docs', labelKey: 'settings.advanced.companyDocs' },
  { to: '/create', labelKey: 'settings.advanced.createAgent' },
  { to: '/timeline', labelKey: 'settings.advanced.timeline' },
  { to: '/cost', labelKey: 'settings.advanced.cost' },
  { to: '/memory', labelKey: 'settings.advanced.memory' },
  { to: '/guardrail', labelKey: 'settings.advanced.guardrail' },
  { to: '/config', labelKey: 'settings.advanced.config' },
  { to: '/trigger', labelKey: 'settings.advanced.trigger' },
]

export function Settings() {
  const { t } = useLanguage()
  const { isHigh, setMode } = useUiMode()
  const [company, setCompany] = useState<CompanyPayload | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    api.getCompany().then(setCompany).catch(() => setCompany(null))
  }, [])

  // Flip ONLY the auto-confirm flag — name/coordinator/cap are re-sent as-is and the
  // backend preserves everything else via load-modify-save (v15 F7).
  const toggleAutoConfirm = (on: boolean) => {
    if (!company) return
    setSaveError(null)
    api
      .saveCompany(company.name, company.coordinator_id, company.team_task_cap_usd, on)
      .then(setCompany)
      .catch((e: unknown) => setSaveError(e instanceof Error ? e.message : t('settings.saveFailed')))
  }

  return (
    <section className="settings-page">
      <PageHeader title={t('settings.title')} />

      <section className="mode-toggle-box">
        <h3>{t('settings.assignSectionTitle')}</h3>
        <label className="mode-toggle">
          <input
            type="checkbox"
            checked={company?.team_task_auto_confirm ?? false}
            disabled={company === null}
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

      {/* Sức khỏe hệ thống — the shared panel: per-integration ok/fail + fix hint (v10 M26). */}
      <IntegrationHealthPanel />
      <p>
        {/* v33 P1: the editable counterpart of the health list — status + key forms. */}
        <Link to="/connections">{t('settings.connectionsLink')}</Link>
      </p>

      <section>
        <h3>{t('settings.advancedSectionTitle')}</h3>
        <p className="muted">{t('settings.advancedSectionHint')}</p>
        <ul className="advanced-links">
          {ADVANCED.map((a) => (
            <li key={a.to}>
              <Link to={a.to}>{t(a.labelKey)}</Link>
            </li>
          ))}
        </ul>
      </section>
    </section>
  )
}
