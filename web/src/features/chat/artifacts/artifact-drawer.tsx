// The artifact drawer: what the agents in THIS room actually produced.
//
// Opened on demand from the thread header — the room index is one request and the
// per-step text another, so nothing here loads until the CEO asks for it.
import { useState } from 'react'
import { useRoomArtifacts } from '../../../api/queries/use-artifact-queries'
import { useLanguage } from '../../../i18n/language-context'
import { StepArtifactView } from './step-artifact-view'

interface Props {
  roomId: string
  open: boolean
  onClose: () => void
}

/** The step the drawer is showing, identified by the pair the API needs. */
export interface SelectedStep {
  taskId: string
  seq: number
  title: string
}

export function ArtifactDrawer({ roomId, open, onClose }: Props) {
  const { t } = useLanguage()
  const { data, isLoading } = useRoomArtifacts(roomId, open)
  const [selected, setSelected] = useState<SelectedStep | null>(null)

  if (!open) return null

  const tasks = data?.tasks ?? []

  return (
    <aside className="artifact-drawer" aria-label={t('artifacts.title')}>
      <header className="artifact-drawer-head">
        <h3 className="chat-pane-title">{t('artifacts.title')}</h3>
        <button type="button" className="artifact-close" onClick={onClose} aria-label={t('artifacts.close')}>
          ✕
        </button>
      </header>

      {isLoading ? <p className="pending-empty">{t('common.loading')}</p> : null}

      {!isLoading && tasks.length === 0 ? (
        <p className="pending-empty">{t('artifacts.empty')}</p>
      ) : null}

      <ul className="artifact-task-list">
        {tasks.map((task) => (
          <li key={task.task_id} className="artifact-task">
            <p className="artifact-task-title" title={task.title}>
              {task.title}
            </p>
            <ul className="artifact-step-list">
              {task.steps.map((step) => (
                <li key={`${task.task_id}-${step.seq}`}>
                  <button
                    type="button"
                    className={`artifact-step${
                      selected?.taskId === task.task_id && selected.seq === step.seq
                        ? ' is-active'
                        : ''
                    }`}
                    onClick={() =>
                      setSelected({ taskId: task.task_id, seq: step.seq, title: step.title })
                    }
                  >
                    <span className="artifact-step-agent">{step.assigned_to}</span>
                    <span className="artifact-step-title" title={step.title}>
                      {step.title}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>

      {selected ? <StepArtifactView step={selected} /> : null}
    </aside>
  )
}
