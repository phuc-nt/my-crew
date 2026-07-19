// CreateAgent wizard (route /create): a state machine (plain useState, no new deps) that
// ends by POSTing /api/agents/create. Steps: Mẫu (optional) → Domain → Identity →
// Reports + schedule → Bindings → Review + create. Each step is its own component under
// src/wizard/ to keep this file small; use-create-agent-wizard.ts owns the shared state.
// Step 0 (template picker) never changes the create path: applyTemplate() only prefills
// wizard state, buildSpec()/api.createAgent are unchanged.
import { DomainPicker } from '../components/DomainPicker'
import { Button } from '../components/ui/button'
import { PageHeader } from '../components/ui/page-header'
import type { UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import { BindingsStep } from '../wizard/BindingsStep'
import { IdentityStep } from '../wizard/IdentityStep'
import { ReportsStep } from '../wizard/ReportsStep'
import { ReviewStep } from '../wizard/ReviewStep'
import { StaffTemplatePicker } from '../wizard/staff-template-picker'
import { ID_PATTERN, useCreateAgentWizard } from '../wizard/use-create-agent-wizard'

const STEP_LABEL_KEYS: UiKey[] = [
  'createAgent.step.template',
  'createAgent.step.domain',
  'createAgent.step.identity',
  'createAgent.step.reports',
  'createAgent.step.bindings',
  'createAgent.step.review',
]

export function CreateAgent() {
  const { t } = useLanguage()
  const wizard = useCreateAgentWizard()
  const {
    state,
    update,
    selectPack,
    applyTemplate,
    goTo,
    toggleReport,
    setCronFor,
    stakeholderChannelMissing,
    buildSpec,
  } = wizard

  const canAdvanceFrom: Record<number, boolean> = {
    0: true,
    1: state.pack !== null,
    2: state.id.trim() !== '' && ID_PATTERN.test(state.id) && state.name.trim() !== '',
    3: true, // reports may be empty (staffer with no scheduled report kind)
    4: true,
    5: false,
  }

  return (
    <section>
      <PageHeader title={t('createAgent.title')} />
      <ol className="wizard-steps">
        {STEP_LABEL_KEYS.map((key, i) => (
          <li key={key} className={state.step === i ? 'wizard-step-active' : undefined}>
            {i}. {t(key)}
          </li>
        ))}
      </ol>

      {state.step === 0 && (
        <StaffTemplatePicker
          onApply={(template, pack) => {
            applyTemplate(template, pack)
            goTo(2) // pack + reports + persona prefilled — skip straight to Identity review
          }}
          onSkip={() => goTo(1)}
        />
      )}
      {state.step === 1 && (
        <DomainPicker selected={state.pack?.id ?? null} onSelect={selectPack} />
      )}
      {state.step === 2 && <IdentityStep state={state} update={update} />}
      {state.step === 3 && (
        <ReportsStep state={state} toggleReport={toggleReport} setCronFor={setCronFor} />
      )}
      {state.step === 4 && (
        <BindingsStep
          state={state}
          update={update}
          stakeholderChannelMissing={stakeholderChannelMissing}
        />
      )}
      {state.step === 5 && <ReviewStep spec={buildSpec()} pack={state.pack} />}

      <div className="wizard-nav">
        {state.step > 0 && (
          <Button variant="ghost" onClick={() => goTo(state.step - 1)}>
            {t('createAgent.back')}
          </Button>
        )}{' '}
        {state.step > 0 && state.step < 5 && (
          <Button variant="ghost" disabled={!canAdvanceFrom[state.step]} onClick={() => goTo(state.step + 1)}>
            {t('createAgent.next')}
          </Button>
        )}
      </div>
    </section>
  )
}
