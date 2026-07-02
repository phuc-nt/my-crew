// CreateAgent wizard (route /create): a 5-step state machine (plain useState, no new
// deps) that ends by POSTing /api/agents/create. Steps: Domain → Identity → Reports +
// schedule → Bindings → Review + create. Each step is its own component under
// src/wizard/ to keep this file small; use-create-agent-wizard.ts owns the shared state.
import { DomainPicker } from '../components/DomainPicker'
import { BindingsStep } from '../wizard/BindingsStep'
import { IdentityStep } from '../wizard/IdentityStep'
import { ReportsStep } from '../wizard/ReportsStep'
import { ReviewStep } from '../wizard/ReviewStep'
import { ID_PATTERN, useCreateAgentWizard } from '../wizard/use-create-agent-wizard'

const STEP_LABELS = ['Domain', 'Identity', 'Reports', 'Bindings', 'Review']

export function CreateAgent() {
  const wizard = useCreateAgentWizard()
  const { state, update, selectPack, goTo, toggleReport, setCronFor, stakeholderChannelMissing, buildSpec } =
    wizard

  const canAdvanceFrom: Record<number, boolean> = {
    1: state.pack !== null,
    2: state.id.trim() !== '' && ID_PATTERN.test(state.id) && state.name.trim() !== '',
    3: state.reports.length > 0,
    4: true,
    5: false,
  }

  return (
    <section>
      <h2>Create agent</h2>
      <ol className="wizard-steps">
        {STEP_LABELS.map((label, i) => (
          <li key={label} className={state.step === i + 1 ? 'wizard-step-active' : undefined}>
            {i + 1}. {label}
          </li>
        ))}
      </ol>

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
        {state.step > 1 && (
          <button type="button" onClick={() => goTo(state.step - 1)}>
            Back
          </button>
        )}{' '}
        {state.step < 5 && (
          <button type="button" disabled={!canAdvanceFrom[state.step]} onClick={() => goTo(state.step + 1)}>
            Next
          </button>
        )}
      </div>
    </section>
  )
}
