// One task, end to end: its steps, what each produced, how the coordinator routed it,
// and what it cost.
//
// Addressed by ROOM id, not task id: the artifact index, the office and the chat thread
// are all keyed by room, and a room holds the task. A room with several tasks renders
// each one — that is real in the store, so the page does not pretend otherwise.
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useRoomArtifacts } from '../../../api/queries/use-artifact-queries'
import { useTaskMetrics, useTaskRoute } from '../../../api/queries/use-work-queries'
import { useLanguage } from '../../../i18n/language-context'
import { formatCost } from '../../../labels'
import type { RoomArtifactTask } from '../../../types'
import { StalledTaskActions } from '../stalled-task-actions'
import { StepProgress } from './step-progress'

/** The first dead (failed/timeout) step's id — same predicate the board card and the
 *  backend serializer use. Absent for a review-exhausted stall; `accept` still works
 *  for that case (the ops layer derives its own target from task state either way). */
function deadStepId(task: RoomArtifactTask): string | undefined {
  return task.steps.find((s) => s.status === 'failed' || s.status === 'timeout')?.step_id
}

/** v88 P5-A: the re-assign seed — the task's own brief (payload only carries `title`,
 *  no separate description) plus the old PIC as an @mention so the new draft keeps the
 *  same target unless the CEO changes it. Exported for the seeding unit test. */
export function reassignSeed(task: RoomArtifactTask): string {
  const mention = task.pic_id ? `@${task.pic_id} ` : ''
  return `${mention}${task.title}`
}

/** The route + metrics funnel for one task — how it was dispatched and what it cost. */
function TaskFunnel({ taskId }: { taskId: string }) {
  const { t } = useLanguage()
  const route = useTaskRoute(taskId)
  const metrics = useTaskMetrics(taskId)
  const m = metrics.data

  return (
    <dl className="task-funnel">
      <div>
        <dt>{t('taskDetail.routeMode')}</dt>
        <dd>{route.data?.mode || '—'}</dd>
      </div>
      <div>
        <dt>{t('taskDetail.routeReason')}</dt>
        <dd>{route.data?.reason || '—'}</dd>
      </div>
      <div>
        <dt>{t('taskDetail.wallClock')}</dt>
        <dd>{m?.wall_clock_text || '—'}</dd>
      </div>
      <div>
        <dt>{t('taskDetail.cost')}</dt>
        <dd>{m ? formatCost(m.cost_usd) : '—'}</dd>
      </div>
      <div>
        <dt>{t('taskDetail.stepSplit')}</dt>
        <dd>
          {m
            ? t('taskDetail.stepSplitValue', {
                content: m.content_steps,
                review: m.review_steps,
                rework: m.rework_steps,
              })
            : '—'}
        </dd>
      </div>
    </dl>
  )
}

function TaskSection(
  { task, showTitle, roomId }: { task: RoomArtifactTask; showTitle: boolean; roomId: string },
) {
  const { t } = useLanguage()
  const navigate = useNavigate()
  const [actionError, setActionError] = useState<string | null>(null)
  const stalledStep = task.steps.find((s) => s.step_id === deadStepId(task))
  return (
    <section className="task-detail-task">
      {showTitle && (
        <h3 className="task-detail-title">
          {task.title} <span className="muted">· {task.status}</span>
        </h3>
      )}
      <p className="muted">
        {task.status}
        {task.pic_id && ` · ${t('taskDetail.owner', { id: task.pic_id })}`}
      </p>
      {/* v88 P5-A: re-assign — navigates to the chat hub's toàn-cảnh composer with the
          old brief + PIC seeded via router state (no new endpoint; the composer's
          existing preview/confirm flow creates a brand-new task from the seed). */}
      <p>
        <button
          type="button"
          className="task-detail-reassign"
          onClick={() =>
            navigate('/chat', { state: { assignSeed: reassignSeed(task) } })
          }
        >
          {t('taskDetail.reassign')}
        </button>
      </p>
      {/* v88 P3: the unstick panel — a stalled task gets its reason + the 4 actions
          right on the page it's already open, no chat detour. Cancel is offered on
          ANY non-terminal task (open/running/stalled), not only stalled — "hủy task"
          is a control the CEO wants on a live task too, not just a stuck one. */}
      {(task.status === 'stalled' || task.status === 'open' || task.status === 'running') && (
        <div className="task-detail-stalled-panel">
          {task.status === 'stalled' && (
            <p className="task-detail-stalled-reason">
              {stalledStep
                ? t('teamKanban.stalledAt', { step: stalledStep.title })
                : t('stalledActions.reviewExhausted')}
            </p>
          )}
          <StalledTaskActions
            taskId={task.task_id}
            stepId={deadStepId(task)}
            roomId={roomId}
            onError={setActionError}
            showRecovery={task.status === 'stalled'}
          />
          {actionError && <p className="error">{actionError}</p>}
        </div>
      )}
      <TaskFunnel taskId={task.task_id} />
      <StepProgress taskId={task.task_id} steps={task.steps} />
    </section>
  )
}

export function TaskDetailPage() {
  const { t } = useLanguage()
  const { room = '' } = useParams<{ room: string }>()
  const { data, isLoading, isError } = useRoomArtifacts(room, Boolean(room))

  const tasks = data?.tasks ?? []

  return (
    <section className="task-detail-page" data-testid="task-detail-page">
      <header className="task-detail-head">
        <Link className="agent-back" to="/work">
          {t('taskDetail.back')}
        </Link>
        {/* The room id is a 12-char hash; the task's own title is what identifies this
            page to a reader, so the hash drops to a subtitle. A room holding several
            tasks falls back to the hash, which is then genuinely the only shared name. */}
        <h2>{tasks.length === 1 ? tasks[0].title : room}</h2>
        {tasks.length === 1 && <p className="muted task-detail-room">{room}</p>}
        <nav className="task-detail-links">
          {/* The two other places this room exists: its chat thread and its desk in 3D. */}
          <Link to={`/chat/${encodeURIComponent(room)}`}>{t('taskDetail.openChat')}</Link>{' '}
          <Link to={`/office?room=${encodeURIComponent(room)}`}>{t('taskDetail.openOffice')}</Link>
        </nav>
      </header>

      {isLoading && <p className="muted">{t('work.loading')}</p>}
      {isError && <p className="error">{t('taskDetail.loadError')}</p>}
      {!isLoading && !isError && tasks.length === 0 && (
        <p className="muted">{t('taskDetail.noTasks')}</p>
      )}

      {tasks.map((task) => (
        <TaskSection key={task.task_id} task={task} showTitle={tasks.length > 1} roomId={room} />
      ))}
    </section>
  )
}
