// One task's steps, in order, each openable.
//
// The step list comes from the ROOM artifact index rather than the board card: the card
// only carries counts (3/5), while the index carries every step's id, type, owner and
// status — which is what turns "3/5" into "who is doing what right now".
import { useState } from 'react'
import { StepArtifactView } from '../../chat/artifacts/step-artifact-view'
import { useLanguage } from '../../../i18n/language-context'
import type { RoomArtifactStep } from '../../../types'

/** Status → the dot's modifier class. Anything unknown stays neutral rather than green. */
function statusClass(status: string): string {
  if (status === 'done') return 'is-done'
  if (status === 'running' || status === 'in_progress') return 'is-running'
  if (status === 'failed' || status === 'error') return 'is-failed'
  return ''
}

interface Props {
  taskId: string
  steps: readonly RoomArtifactStep[]
}

export function StepProgress({ taskId, steps }: Props) {
  const { t } = useLanguage()
  const [open, setOpen] = useState<RoomArtifactStep | null>(null)

  if (steps.length === 0) return <p className="muted">{t('taskDetail.noSteps')}</p>

  return (
    <div className="step-progress">
      <ol className="step-list">
        {steps.map((s) => (
          <li key={s.step_id} className={`step-row ${statusClass(s.status)}`}>
            <button
              type="button"
              className="step-open"
              aria-pressed={open?.step_id === s.step_id}
              onClick={() => setOpen((cur) => (cur?.step_id === s.step_id ? null : s))}
            >
              <span className="step-dot" aria-hidden="true" />
              <span className="step-seq">{s.seq}</span>
              <span className="step-title">{s.title}</span>
              <span className="step-meta muted">
                {s.assigned_to && `@${s.assigned_to}`} · {s.step_type} · {s.status}
              </span>
            </button>
          </li>
        ))}
      </ol>

      {/* The artifact + 🔬 transcript for the open step — the same renderer the chat
          drawer uses, so a step reads identically wherever it is opened from. */}
      {open && (
        <StepArtifactView step={{ taskId, seq: open.seq, title: open.title }} />
      )}
    </div>
  )
}
