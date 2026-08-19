// One task, end to end: its steps, what each produced, how the coordinator routed it,
// and what it cost.
//
// Addressed by ROOM id, not task id: the artifact index, the office and the chat thread
// are all keyed by room, and a room holds the task. A room with several tasks renders
// each one — that is real in the store, so the page does not pretend otherwise.
import { Link, useParams } from 'react-router'
import { useRoomArtifacts } from '../../../api/queries/use-artifact-queries'
import { useTaskMetrics, useTaskRoute } from '../../../api/queries/use-work-queries'
import { useLanguage } from '../../../i18n/language-context'
import { formatCost } from '../../../labels'
import type { RoomArtifactTask } from '../../../types'
import { StepProgress } from './step-progress'

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

function TaskSection({ task, showTitle }: { task: RoomArtifactTask; showTitle: boolean }) {
  const { t } = useLanguage()
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
        <TaskSection key={task.task_id} task={task} showTitle={tasks.length > 1} />
      ))}
    </section>
  )
}
