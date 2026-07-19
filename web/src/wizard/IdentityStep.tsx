// Wizard Step 2: agent id/name + an optional persona helper. Typing role + goals
// regenerates the SOUL.md textarea (deterministic template, no LLM) until the operator
// edits the textarea by hand — after that we stop overwriting their edits. `personaEdited`
// lives in the wizard's shared state (not a local useState) so it survives this step
// unmounting when the operator navigates Back/Next and returns.
import { useLanguage } from '../i18n/language-context'
import { generateSoulMarkdown } from './persona-template'
import { ID_PATTERN } from './use-create-agent-wizard'
import type { WizardState } from './use-create-agent-wizard'

export function IdentityStep({
  state,
  update,
}: {
  state: WizardState
  update: <K extends keyof WizardState>(key: K, value: WizardState[K]) => void
}) {
  const { t } = useLanguage()
  const idValid = state.id === '' || ID_PATTERN.test(state.id)

  function regenerate(role: string, goals: string) {
    if (!state.personaEdited) update('persona', generateSoulMarkdown(role, goals))
  }

  return (
    <section>
      <h3>{t('identityStep.title')}</h3>
      <label>
        {t('identityStep.idLabel')}{' '}
        <input
          value={state.id}
          onChange={(e) => update('id', e.target.value.toLowerCase())}
          placeholder="sales-pm"
        />
      </label>
      {!idValid && <p className="error">{t('identityStep.idInvalid')}</p>}
      <br />
      <label>
        {t('identityStep.nameLabel')}{' '}
        <input
          value={state.name}
          onChange={(e) => update('name', e.target.value)}
          placeholder={t('identityStep.namePlaceholder')}
        />
      </label>
      <h4>{t('identityStep.personaHintTitle')}</h4>
      <label>
        {t('identityStep.roleLabel')}{' '}
        <input
          value={state.role}
          onChange={(e) => {
            update('role', e.target.value)
            regenerate(e.target.value, state.goals)
          }}
          placeholder={t('identityStep.rolePlaceholder')}
        />
      </label>
      <br />
      <label>
        {t('identityStep.goalsLabel')}{' '}
        <textarea
          value={state.goals}
          onChange={(e) => {
            update('goals', e.target.value)
            regenerate(state.role, e.target.value)
          }}
          rows={3}
        />
      </label>
      <h4>{t('identityStep.runtimeSectionTitle')}</h4>
      <label>
        {t('identityStep.runtimeLabel')}{' '}
        <select value={state.agentRuntime} onChange={(e) => update('agentRuntime', e.target.value)}>
          <option value="native">{t('identityStep.runtimeNative')}</option>
          <option value="create_agent">{t('identityStep.runtimeCreateAgent')}</option>
          <option value="deep_agent">{t('identityStep.runtimeDeepAgent')}</option>
        </select>
      </label>
      <p className="runtime-hint">
        {state.agentRuntime === 'native' && t('identityStep.runtimeHintNative')}
        {state.agentRuntime === 'create_agent' && t('identityStep.runtimeHintCreateAgent')}
        {state.agentRuntime === 'deep_agent' && t('identityStep.runtimeHintDeepAgent')}
      </p>
      {/* v50: deep_team (v43) — only meaningful for deep_agent, so gate the toggle on it. */}
      {state.agentRuntime === 'deep_agent' && (
        <label className="wizard-inline-check">
          <input
            type="checkbox"
            checked={state.deepTeam}
            onChange={(e) => update('deepTeam', e.target.checked)}
          />{' '}
          {t('identityStep.deepTeamLabel')}
        </label>
      )}
      <h4>{t('identityStep.actionModeSectionTitle')}</h4>
      <label>
        {t('identityStep.trustModeLabel')}{' '}
        <select
          value={state.trustMode}
          onChange={(e) => update('trustMode', e.target.value as '' | 'autonomous' | 'guarded')}
        >
          <option value="">{t('identityStep.trustModeDefault')}</option>
          <option value="autonomous">{t('identityStep.trustModeAutonomous')}</option>
          <option value="guarded">{t('identityStep.trustModeGuarded')}</option>
        </select>
      </label>
      <p className="runtime-hint">
        {state.trustMode === 'autonomous' && t('identityStep.trustModeHintAutonomous')}
        {state.trustMode === 'guarded' && t('identityStep.trustModeHintGuarded')}
        {state.trustMode === '' && t('identityStep.trustModeHintDefault')}
      </p>
      <h4>{t('identityStep.soulSectionTitle')}</h4>
      <textarea
        className="persona-textarea"
        value={state.persona}
        onChange={(e) => {
          update('personaEdited', true)
          update('persona', e.target.value)
        }}
        rows={8}
      />
    </section>
  )
}
