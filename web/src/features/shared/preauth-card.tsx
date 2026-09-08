// v94: the pre-authorization card on the assign preview. Lists what each drafted step
// MAY do (write outside, run shell, search web, send mail, get reviewed) so the CEO
// decides the approval posture ONCE, up front, instead of being paged per Action
// Gateway gate mid-run. The choice travels with confirm as `preauth_scope`:
//   ''       ask at every gate (the default, unchanged behaviour)
//   'once'   approve every gate of THIS task
//   'always' approve AND learn an ApprovalRule from each gated action for next time
// The server still lets a learned DENY rule and the per-task CEO opt-out win over
// either scope — this card only carries the CEO's intent, it enforces nothing.
import type { UiKey } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'
import type { AssignManifest, AssignManifestStep, PreauthScope } from '../../types'

export const PREAUTH_FLAGS = [
  'external_write', 'needs_shell', 'needs_web', 'needs_mail', 'needs_review',
] as const satisfies readonly (keyof AssignManifestStep)[]

export const PREAUTH_SCOPES: readonly PreauthScope[] = ['', 'once', 'always']

/** The flags a step actually carries, in display order. Exported for the unit test. */
export function stepFlags(step: AssignManifestStep): (typeof PREAUTH_FLAGS)[number][] {
  return PREAUTH_FLAGS.filter((f) => step[f])
}

/** A scope only makes sense when at least one step will hit a gate. */
export function scopeChoiceNeeded(manifest: AssignManifest | undefined): boolean {
  return (manifest?.external_count ?? 0) > 0
}

interface Props {
  manifest: AssignManifest | undefined
  scope: PreauthScope
  onScopeChange: (scope: PreauthScope) => void
}

export function PreauthCard({ manifest, scope, onScopeChange }: Props) {
  const { t } = useLanguage()
  if (!manifest) return null
  const steps = manifest.steps
  const needsChoice = scopeChoiceNeeded(manifest)
  return (
    <div className="preauth-card" data-testid="preauth-card">
      <p className="preauth-title">{t('preauth.title')}</p>
      {steps.length === 0 ? (
        <p className="preauth-none muted">{t('preauth.noSteps')}</p>
      ) : (
        <ul className="preauth-steps">
          {steps.map((s) => {
            const flags = stepFlags(s)
            return (
              <li key={s.step_id} className={`preauth-step${s.external_write ? ' is-external' : ''}`}>
                <span className="preauth-step-title">{s.title}</span>
                {s.assigned_to && <span className="preauth-step-who muted">@{s.assigned_to}</span>}
                {flags.length === 0 ? (
                  <span className="preauth-flag is-internal">{t('preauth.flag.internal')}</span>
                ) : (
                  flags.map((f) => (
                    <span key={f} className={`preauth-flag is-${f}`}>
                      {t(`preauth.flag.${f}` as UiKey)}
                    </span>
                  ))
                )}
              </li>
            )
          })}
        </ul>
      )}
      {needsChoice ? (
        <fieldset className="preauth-scope" data-testid="preauth-scope">
          <legend>{t('preauth.externalCount', { n: manifest.external_count })}</legend>
          {PREAUTH_SCOPES.map((value) => (
            <label key={value || 'none'} className={`preauth-choice${scope === value ? ' is-on' : ''}`}>
              <input
                type="radio"
                name="preauth-scope"
                value={value}
                checked={scope === value}
                onChange={() => onScopeChange(value)}
              />
              <span className="preauth-choice-label">
                {t(`preauth.scope.${value || 'none'}` as UiKey)}
              </span>
              <span className="preauth-choice-hint muted">
                {t(`preauth.scopeHint.${value || 'none'}` as UiKey)}
              </span>
            </label>
          ))}
        </fieldset>
      ) : steps.length > 0 ? (
        <p className="preauth-none muted">{t('preauth.noGates')}</p>
      ) : null}
    </div>
  )
}
