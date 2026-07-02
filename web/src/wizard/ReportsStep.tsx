// Wizard Step 3: checkboxes for the selected pack's report_kinds; each checked kind gets
// an optional ScheduleBuilder. No schedule entry for a kind = manual-only trigger.
import { ScheduleBuilder } from '../components/ScheduleBuilder'
import type { WizardState } from './use-create-agent-wizard'

export function ReportsStep({
  state,
  toggleReport,
  setCronFor,
}: {
  state: WizardState
  toggleReport: (kind: string) => void
  setCronFor: (kind: string, cron: string | null) => void
}) {
  const kinds = state.pack?.report_kinds ?? []
  return (
    <section>
      <h3>Step 3: Reports + schedule</h3>
      {kinds.length === 0 && <p className="muted">Selected pack serves no report kinds.</p>}
      {kinds.map((kind) => {
        const checked = state.reports.includes(kind)
        return (
          <div key={kind} className="reports-step-kind">
            <label>
              <input type="checkbox" checked={checked} onChange={() => toggleReport(kind)} /> {kind}
            </label>
            {checked && <ScheduleBuilder kind={kind} onChange={(cron) => setCronFor(kind, cron)} />}
          </div>
        )
      })}
    </section>
  )
}
