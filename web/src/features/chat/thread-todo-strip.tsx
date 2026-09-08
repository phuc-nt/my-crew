// v94: the task plan pinned under a workroom's thread — every task in the room with its
// steps and a done/total count, so the CEO sees where the work stands without opening
// the artifact drawer or the work hub. Reads the room's artifact index (the same rows
// the drawer and the task detail page use); the SSE bridge invalidates that slice on
// every progress kind, so a step finishing moves the strip live.
import { useState } from 'react'
import { useRoomArtifacts } from '../../api/queries/use-artifact-queries'
import { useLanguage } from '../../i18n/language-context'
import type { RoomArtifactStep, RoomArtifactTask } from '../../types'
import { OVERVIEW_ROOM_ID } from './chat-state'

const TERMINAL_STEP = new Set(['done', 'skipped', 'dropped'])

/** Steps that count as finished for the progress fraction. Exported for the unit test. */
export function doneCount(steps: readonly RoomArtifactStep[]): number {
  return steps.filter((s) => s.status === 'done').length
}

export function stepMark(status: string): string {
  if (status === 'done') return '✓'
  if (status === 'running' || status === 'in_progress') return '▶'
  if (status === 'failed' || status === 'timeout' || status === 'error') return '✕'
  if (status === 'awaiting_approval') return '⏸'
  if (TERMINAL_STEP.has(status)) return '–'
  return '○'
}

function TaskTodo({ task }: { task: RoomArtifactTask }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(task.status !== 'done')
  const done = doneCount(task.steps)
  const total = task.steps.length
  const pct = total ? Math.round((done / total) * 100) : 0
  return (
    <li className={`todo-task is-${task.status}`} data-testid="todo-task">
      <button
        type="button"
        className="todo-task-head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="todo-task-title">{task.title}</span>
        <span className="todo-task-progress" data-testid="todo-progress">
          {t('todoStrip.progress', { done, total })}
        </span>
        <span className="todo-task-bar" aria-hidden="true">
          <span className="todo-task-bar-fill" style={{ width: `${pct}%` }} />
        </span>
      </button>
      {open && total > 0 ? (
        <ol className="todo-steps">
          {task.steps.map((s) => (
            <li key={s.step_id} className={`todo-step is-${s.status}`}>
              <span className="todo-step-mark" aria-hidden="true">{stepMark(s.status)}</span>
              <span className="todo-step-title">{s.title}</span>
              {s.assigned_to && <span className="todo-step-who muted">@{s.assigned_to}</span>}
            </li>
          ))}
        </ol>
      ) : null}
    </li>
  )
}

export function ThreadTodoStrip({ roomId }: { roomId: string }) {
  const { t } = useLanguage()
  const enabled = roomId !== OVERVIEW_ROOM_ID
  const { data } = useRoomArtifacts(roomId, enabled)
  const tasks = data?.tasks ?? []
  if (!enabled || tasks.length === 0) return null
  return (
    <div className="thread-todo-strip" data-testid="thread-todo-strip">
      <p className="thread-todo-label">{t('todoStrip.label')}</p>
      <ul className="todo-tasks">
        {tasks.map((task) => <TaskTodo key={task.task_id} task={task} />)}
      </ul>
    </div>
  )
}
