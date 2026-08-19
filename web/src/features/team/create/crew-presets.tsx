// The crew banner: a whole default team in ≤3 clicks (preview → confirm → created).
// A manifest may ship more than one crew (office / personal), so the banner previews
// whichever is selected and creates exactly that one.
import { useState } from 'react'
import { useCreateCrew, useCrewPreview, useCrews } from '../../../api/queries/use-team-queries'
import { Button } from '../../../components/ui/button'
import { useLanguage } from '../../../i18n/language-context'
import type { CrewCreateResult } from '../../../types'

export function CrewPresets() {
  const { t } = useLanguage()
  const { data: crewList } = useCrews()
  // null = the default crew; a string switches the preview to that manifest.
  const [crewId, setCrewId] = useState<string | null>(null)
  const { data: crew } = useCrewPreview(crewId)
  const createCrew = useCreateCrew()
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<CrewCreateResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const crews = crewList?.crews ?? []

  async function create() {
    setError(null)
    try {
      setResult(await createCrew.mutateAsync(crew?.crew_id))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('staffTemplatePicker.crewCreateFailed'))
    }
  }

  if (result) {
    return (
      <div className="crew-banner">
        {t('staffTemplatePicker.crewCreatedMsg', { n: result.created.length })}
        {result.skipped.length > 0
          ? t('staffTemplatePicker.crewSkippedSuffix', { n: result.skipped.length })
          : ''}
        {result.coordinator_id
          ? t('staffTemplatePicker.crewCoordinatorSuffix', { id: result.coordinator_id })
          : ''}
        {result.failed.length > 0 && (
          <p className="error">
            {t('staffTemplatePicker.crewFailedPrefix')}
            {result.failed.map((f) => `${f.role_id} (${f.error})`).join('; ')}
          </p>
        )}
      </div>
    )
  }

  if (!crew) return null
  const missing = crew.members.filter((m) => !m.exists).length
  // Nothing to offer: the crew is fully staffed and there is no second crew to switch to.
  if (missing === 0 && crews.length <= 1) return null

  return (
    <div className="crew-banner">
      {error && <p className="error">{t('staffTemplatePicker.errorPrefix', { message: error })}</p>}
      <strong>{crew.crew}</strong>{' '}
      {crews.length > 1 && (
        <span className="crew-switch">
          {crews.map((c) => (
            <Button
              key={c.id}
              variant="chip"
              disabled={c.id === crew.crew_id}
              // Collapse the confirm panel: it describes the OLD crew's member list, and
              // leaving it open lets it narrate a crew the user is no longer looking at.
              onClick={() => {
                setOpen(false)
                setCrewId(c.id)
              }}
            >
              {c.name}
            </Button>
          ))}
        </span>
      )}{' '}
      {missing === 0 ? (
        <span className="muted">{t('staffTemplatePicker.crewAllExist')}</span>
      ) : !open ? (
        <Button variant="ghost" onClick={() => setOpen(true)}>
          {t('staffTemplatePicker.crewCreateAll', { n: missing })}
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
          <Button variant="ghost" disabled={createCrew.isPending} onClick={() => void create()}>
            {createCrew.isPending
              ? t('staffTemplatePicker.creating')
              : t('staffTemplatePicker.crewConfirmCreate', { n: missing })}
          </Button>{' '}
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {t('staffTemplatePicker.crewCancel')}
          </Button>
        </div>
      )}
    </div>
  )
}
