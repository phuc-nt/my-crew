// The template gallery: one card per role, each createable in two clicks (Tạo ngay →
// confirm). The server builds the spec from role_id, so nothing here can produce an
// agent the validated create door would have rejected.
import { useState } from 'react'
import { ApiError } from '../../../api/client'
import { useCreateFromTemplate, useStaffTemplates } from '../../../api/queries/use-team-queries'
import { Button } from '../../../components/ui/button'
import { Card } from '../../../components/ui/card'
import { useLanguage } from '../../../i18n/language-context'
import type { StaffTemplate } from '../../../types'
import { templateChips } from './template-chips'

export function TemplateGallery({ onCustomize }: { onCustomize?: (t: StaffTemplate) => void }) {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useStaffTemplates()
  const create = useCreateFromTemplate()
  const [confirming, setConfirming] = useState<string | null>(null)
  const [created, setCreated] = useState<Record<string, string>>({})
  // A 409 means the id is taken. Rather than dead-ending on the message, the card offers
  // one more click that creates `<role_id>-2` — a SECOND staffer of the same role, which
  // is what someone clicking a role card twice actually wants.
  const [conflictOf, setConflictOf] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function quickCreate(template: StaffTemplate, idOverride?: string) {
    setError(null)
    try {
      const out = await create.mutateAsync({ roleId: template.role_id, agentId: idOverride })
      setCreated((m) => ({
        ...m,
        [template.role_id]: t('staffTemplatePicker.createdMsg', { id: out.id, hint: out.hint }),
      }))
      setConfirming(null)
      setConflictOf(null)
    } catch (e) {
      if (!idOverride && e instanceof ApiError && e.status === 409) setConflictOf(template.role_id)
      setError(e instanceof Error ? e.message : t('staffTemplatePicker.createFromTemplateFailed'))
    }
  }

  if (isLoading) return <p>{t('staffTemplatePicker.loading')}</p>
  const templates = data?.templates ?? []
  if (isError && templates.length === 0)
    return <p className="error">{t('staffTemplatePicker.createFromTemplateFailed')}</p>
  if (templates.length === 0) return <p className="muted">{t('staffTemplatePicker.noTemplates')}</p>

  return (
    <>
      {error && <p className="error">{t('staffTemplatePicker.errorPrefix', { message: error })}</p>}
      <div className="staff-template-grid">
        {templates.map((template) => {
          const busy = create.isPending && create.variables?.roleId === template.role_id
          return (
            <Card key={template.role_id} className="staff-template-card">
              <strong>{template.role}</strong>
              <div className="muted">
                {t('staffTemplatePicker.domainLabel', { domain: template.domain })}
              </div>
              <div className="template-chips">
                {templateChips(template, t).map((c) => (
                  <span key={c} className="chip">{c}</span>
                ))}
              </div>
              {created[template.role_id] ? (
                <p className="muted">✅ {created[template.role_id]}</p>
              ) : confirming === template.role_id ? (
                <div>
                  <p className="muted">
                    {t('staffTemplatePicker.confirmCreatePrompt', { id: template.role_id })}
                  </p>
                  <Button variant="ghost" disabled={busy} onClick={() => void quickCreate(template)}>
                    {busy ? t('staffTemplatePicker.creating') : t('staffTemplatePicker.confirm')}
                  </Button>{' '}
                  <Button variant="ghost" onClick={() => setConfirming(null)}>
                    {t('staffTemplatePicker.crewCancel')}
                  </Button>
                  {conflictOf === template.role_id && (
                    <p className="muted">
                      {t('staffTemplatePicker.alreadyExists', { id: template.role_id })}{' '}
                      <Button
                        variant="ghost"
                        disabled={busy}
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
                  {onCustomize && (
                    <Button variant="chip" onClick={() => onCustomize(template)}>
                      {t('staffTemplatePicker.customize')}
                    </Button>
                  )}
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </>
  )
}
