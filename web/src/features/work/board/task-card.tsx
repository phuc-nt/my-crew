// One task on the board.
//
// The card surfaces the two fields the old kanban buried and the plan asked for: the
// coordinator queue position (waiting is not the same as stuck) and the count of steps
// that escalate to the Docker sandbox tier. Clicking opens the task's own page rather
// than jumping straight to the 3D office — the detail page links onward to the room.
import { Link } from 'react-router'
import { useLanguage } from '../../../i18n/language-context'
import type { TeamBoardCard } from '../../../types'

export function TaskCard({ card, lane }: { card: TeamBoardCard; lane?: string }) {
  const { t } = useLanguage()
  const queued = card.queue_position ?? 0
  const sandbox = card.steps_needs_shell ?? 0
  // Percent, not a fraction of a bar's width: a task with no steps yet must not render
  // a full bar just because 0/0 divides badly.
  const progress = card.steps_total > 0 ? (card.steps_done / card.steps_total) * 100 : 0

  // A stuck task can be 22/23 steps in — a full green bar would read as "finished",
  // which is the opposite of what the lane means. Measured on the real fleet: every
  // card in the stuck lane had a near-complete bar.
  const stuck = lane === 'khac'

  return (
    <li className={`task-card${stuck ? ' is-stuck' : ''}`}>
      <Link className="task-card-link" to={`/work/task/${encodeURIComponent(card.room_id)}`}>
        <span className="task-card-title">{card.title}</span>
        <span className="task-card-meta">
          {card.pic_id && <span className="task-card-pic">@{card.pic_id}</span>}
          {card.steps_total > 0 && (
            <span className="muted">
              {t('teamKanban.stepsDone', { done: card.steps_done, total: card.steps_total })}
            </span>
          )}
        </span>
        {card.steps_total > 0 && (
          <span className="task-card-bar" aria-hidden="true">
            <span
              className={`task-card-bar-fill${stuck ? ' is-stuck' : ''}`}
              style={{ width: `${progress}%` }}
            />
          </span>
        )}
        <span className="task-card-badges">
          {/* Position 0 means "next up", which is not worth a badge — only a real wait is. */}
          {queued >= 1 && (
            <span className="task-badge queued" title={t('teamKanban.queuedTitle')}>
              {t('teamKanban.queuedBehind', { n: queued })}
            </span>
          )}
          {sandbox > 0 && (
            <span className="task-badge sandbox" title={t('teamKanban.sandboxTitle')}>
              {t('teamKanban.sandboxBadge', { n: sandbox })}
            </span>
          )}
        </span>
      </Link>
    </li>
  )
}
