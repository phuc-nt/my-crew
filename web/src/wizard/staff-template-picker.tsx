// Step 0 of the create flow (v32): template cards are now EXECUTABLE, not just prefill.
// Each card offers "Tạo ngay" (one-click: confirm → POST /api/agents/create-from-template
// — the server builds the spec from the template, the client sends only role_id) and
// "Tuỳ chỉnh…" (the old prefill path through the full wizard, unchanged). A crew banner
// on top creates the whole default crew in ≤3 clicks (preview → confirm). Every create
// still goes through the same validated create_agent door server-side.
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { ApiError, api } from '../api/client'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import type { UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import type { CrewCreateResult, CrewPreview, Pack, StaffTemplate } from '../types'

const RUNTIME_LABEL_KEY: Record<string, UiKey> = {
  native: 'staffTemplatePicker.runtimeNative',
  create_agent: 'staffTemplatePicker.runtimeCreateAgent',
  deep_agent: 'staffTemplatePicker.runtimeDeepAgent',
}

/** Chips describing the template's pre-attached tools — the "tool gắn sẵn" contract. */
function toolChips(template: StaffTemplate, t: (key: UiKey, params?: Record<string, string | number>) => string): string[] {
  const chips: string[] = []
  if (template.web_search) chips.push(t('staffTemplatePicker.chipWebSearch'))
  if (template.academic_search) chips.push(t('staffTemplatePicker.chipAcademicSearch'))
  if (template.has_skills) chips.push(t('staffTemplatePicker.chipSkills'))
  if (template.reports.length > 0) chips.push(t('staffTemplatePicker.chipReports', { kinds: template.reports.join(', ') }))
  const runtimeKey = RUNTIME_LABEL_KEY[template.recommended_runtime]
  chips.push(runtimeKey ? t(runtimeKey) : template.recommended_runtime)
  return chips
}

export function StaffTemplatePicker({
  onApply,
  onSkip,
}: {
  onApply: (template: StaffTemplate, pack: Pack) => void
  onSkip: () => void
}) {
  const { t } = useLanguage()
  const [templates, setTemplates] = useState<StaffTemplate[]>([])
  const [packs, setPacks] = useState<Pack[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // one-click state: which card is asking for confirm / creating / done
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [createdMsg, setCreatedMsg] = useState<Record<string, string>>({})
  // crew state
  const [crew, setCrew] = useState<CrewPreview | null>(null)
  const [crewOpen, setCrewOpen] = useState(false)
  const [crewBusy, setCrewBusy] = useState(false)
  const [crewResult, setCrewResult] = useState<CrewCreateResult | null>(null)
  // Conflict retry: id taken → one more click creates `<role_id>-2` (a second staffer
  // of the same role) instead of dead-ending on the 409 message.
  const [conflictOf, setConflictOf] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.getStaffTemplates(), api.getPacks()])
      .then(([templatesRes, packsRes]) => {
        setTemplates(templatesRes.templates)
        setPacks(packsRes.packs)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('staffTemplatePicker.loadFailed')))
      .finally(() => setLoading(false))
    api.getCrewPreview().then(setCrew).catch(() => setCrew(null)) // no crew.yaml ⇒ no banner
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) return <p>{t('staffTemplatePicker.loading')}</p>

  // A fetch failure must not dead-end the wizard: manual path stays reachable.
  if (error && templates.length === 0) {
    return (
      <section>
        <p className="error">{t('staffTemplatePicker.errorPrefix', { message: error })}</p>
        <div className="wizard-nav">
          <Button variant="ghost" onClick={onSkip}>
            {t('staffTemplatePicker.skipChoose')}
          </Button>
        </div>
      </section>
    )
  }

  function customize(template: StaffTemplate) {
    const pack = packs.find((p) => p.id === template.domain)
    if (!pack) {
      setError(t('staffTemplatePicker.packMissing', { role: template.role, domain: template.domain }))
      return
    }
    onApply(template, pack)
  }

  async function quickCreate(template: StaffTemplate, idOverride?: string) {
    setBusy(template.role_id)
    setError(null)
    try {
      const out = idOverride
        ? await api.createFromTemplate(template.role_id, idOverride)
        : await api.createFromTemplate(template.role_id)
      setCreatedMsg((m) => ({
        ...m,
        [template.role_id]: t('staffTemplatePicker.createdMsg', { id: out.id, hint: out.hint }),
      }))
      setConfirming(null)
      setConflictOf(null)
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('staffTemplatePicker.createFromTemplateFailed')
      if (!idOverride && e instanceof ApiError && e.status === 409) {
        setConflictOf(template.role_id)
      }
      setError(msg)
    } finally {
      setBusy(null)
    }
  }

  async function crewCreate() {
    setCrewBusy(true)
    setError(null)
    try {
      setCrewResult(await api.createCrew())
    } catch (e) {
      setError(e instanceof Error ? e.message : t('staffTemplatePicker.crewCreateFailed'))
    } finally {
      setCrewBusy(false)
    }
  }

  const missingCount = crew ? crew.members.filter((m) => !m.exists).length : 0

  return (
    <section>
      <h3>{t('staffTemplatePicker.title')}</h3>
      {error && <p className="error">{t('staffTemplatePicker.errorPrefix', { message: error })}</p>}

      {crew && missingCount > 0 && !crewResult && (
        <div className="crew-banner">
          <strong>{crew.crew}</strong>{' '}
          {!crewOpen ? (
            <Button variant="ghost" onClick={() => setCrewOpen(true)}>
              {t('staffTemplatePicker.crewCreateAll', { n: missingCount })}
            </Button>
          ) : (
            <div className="crew-preview">
              <ul>
                {crew.members.map((m) => (
                  <li key={m.role_id}>
                    {m.role} ({m.role_id})
                    {m.role_id === crew.coordinator ? t('staffTemplatePicker.coordinatorSuffix') : ''}
                    {m.exists ? t('staffTemplatePicker.existingSuffix') : ''}
                  </li>
                ))}
              </ul>
              <Button variant="ghost" disabled={crewBusy} onClick={() => void crewCreate()}>
                {crewBusy
                  ? t('staffTemplatePicker.creating')
                  : t('staffTemplatePicker.crewConfirmCreate', { n: missingCount })}
              </Button>{' '}
              <Button variant="ghost" onClick={() => setCrewOpen(false)}>
                {t('staffTemplatePicker.crewCancel')}
              </Button>
            </div>
          )}
        </div>
      )}
      {crewResult && (
        <div className="crew-banner">
          {t('staffTemplatePicker.crewCreatedMsg', { n: crewResult.created.length })}
          {crewResult.skipped.length > 0
            ? t('staffTemplatePicker.crewSkippedSuffix', { n: crewResult.skipped.length })
            : ''}
          {crewResult.coordinator_id
            ? t('staffTemplatePicker.crewCoordinatorSuffix', { id: crewResult.coordinator_id })
            : ''}
          {crewResult.failed.length > 0 && (
            <p className="error">
              {t('staffTemplatePicker.crewFailedPrefix')}
              {crewResult.failed.map((f) => `${f.role_id} (${f.error})`).join('; ')}
            </p>
          )}
          <p>
            {t('staffTemplatePicker.envTokenHint')}
            <Link to="/team">{t('staffTemplatePicker.teamPageLink')}</Link>
          </p>
        </div>
      )}

      {templates.length === 0 ? (
        <p className="muted">{t('staffTemplatePicker.noTemplates')}</p>
      ) : (
        <div className="staff-template-grid">
          {templates.map((template) => (
            <Card key={template.role_id} className="staff-template-card">
              <strong>{template.role}</strong>
              <div className="muted">{t('staffTemplatePicker.domainLabel', { domain: template.domain })}</div>
              <div className="template-chips">
                {toolChips(template, t).map((c) => (
                  <span key={c} className="chip">
                    {c}
                  </span>
                ))}
              </div>
              {createdMsg[template.role_id] ? (
                <p className="muted">✅ {createdMsg[template.role_id]}</p>
              ) : confirming === template.role_id ? (
                <div>
                  <p className="muted">
                    {t('staffTemplatePicker.confirmCreatePrompt', { id: template.role_id })}
                  </p>
                  <Button
                    variant="ghost"
                    disabled={busy === template.role_id}
                    onClick={() => void quickCreate(template)}
                  >
                    {busy === template.role_id ? t('staffTemplatePicker.creating') : t('staffTemplatePicker.confirm')}
                  </Button>{' '}
                  <Button variant="ghost" onClick={() => setConfirming(null)}>
                    {t('staffTemplatePicker.crewCancel')}
                  </Button>
                  {conflictOf === template.role_id && (
                    <p className="muted">
                      {t('staffTemplatePicker.alreadyExists', { id: template.role_id })}{' '}
                      <Button
                        variant="ghost"
                        disabled={busy === template.role_id}
                        onClick={() => void quickCreate(template, `${template.role_id}-2`)}
                      >
                        {t('staffTemplatePicker.createAnother', { id: `${template.role_id}-2` })}
                      </Button>
                    </p>
                  )}
                </div>
              ) : (
                <div>
                  <Button variant="ghost" onClick={() => setConfirming(template.role_id)}>
                    {t('staffTemplatePicker.createNow')}
                  </Button>{' '}
                  <Button variant="chip" onClick={() => customize(template)}>
                    {t('staffTemplatePicker.customize')}
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
      <div className="wizard-nav">
        <Button variant="ghost" onClick={onSkip}>
          {t('staffTemplatePicker.skipChoose')}
        </Button>
      </div>
    </section>
  )
}
