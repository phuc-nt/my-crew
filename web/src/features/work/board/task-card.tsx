// One task on the board.
//
// The card surfaces the two fields the old kanban buried and the plan asked for: the
// coordinator queue position (waiting is not the same as stuck) and the count of steps
// that escalate to the Docker sandbox tier. Clicking opens the task's own page rather
// than jumping straight to the 3D office — the detail page links onward to the room.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '../../../api/client'
import { queryKeys } from '../../../api/queries/query-keys'
import { useLanguage } from '../../../i18n/language-context'
import type { TeamBoardCard } from '../../../types'
import { StalledTaskActions } from '../stalled-task-actions'

export function TaskCard({ card, lane }: { card: TeamBoardCard; lane?: string }) {
  const { t } = useLanguage()
  const qc = useQueryClient()
  const [dismissing, setDismissing] = useState(false)
  const queued = card.queue_position ?? 0
  const sandbox = card.steps_needs_shell ?? 0
  // Percent, not a fraction of a bar's width: a task with no steps yet must not render
  // a full bar just because 0/0 divides badly.
  const progress = card.steps_total > 0 ? (card.steps_done / card.steps_total) * 100 : 0

  // A stuck task can be 22/23 steps in — a full green bar would read as "finished",
  // which is the opposite of what the lane means. Measured on the real fleet: every
  // card in the stuck lane had a near-complete bar.
  const stuck = lane === 'khac'

  // Bản nháp là kế hoạch đã xem trước nhưng chưa bấm xác nhận. Nó nằm cùng bảng với việc
  // thật nên nhìn y hệt, và trước đây không có đường bỏ nó đi từ bảng — chỉ có màn giao
  // việc đang mở mới hủy được. Nút này mở đúng đường đó ra cho bản nháp đã bỏ dở.
  const draft = lane === 'planning'

  const dismiss = () => {
    setDismissing(true)
    api
      .assignCancel(card.task_id)
      .catch(() => undefined) // dọn nháp là best-effort, giống lúc hủy ở màn giao việc
      .finally(() => {
        setDismissing(false)
        // Bảng tự vẽ lại từ backend: nháp đã terminal thì biến khỏi cột, còn nếu điều phối
        // viên vừa kịp xác nhận nó thì thẻ vẫn còn — đúng thực tế, không tự xoá lạc quan.
        void qc.invalidateQueries({ queryKey: queryKeys.tasks.board() })
      })
  }

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
      {draft && (
        <button
          type="button"
          className="task-card-dismiss"
          onClick={dismiss}
          disabled={dismissing}
        >
          {dismissing ? t('board.dismissingDraft') : t('board.dismissDraft')}
        </button>
      )}
      {/* v88 P3: a stuck task's unstick cluster right on the card — no chat detour.
          card.status carries the real store status ('stalled'), independent of the
          `stuck` local var above (which is lane-derived and also true for the `khac`
          side lane in general). card.stalled_step is the dead step's TITLE (display
          only, routes_outputs.py's board serializer) — NOT its step_id, so it is never
          passed as StalledTaskActions' `stepId` prop; that prop is left unset and the
          component falls back to its own stable URL placeholder. */}
      {card.status === 'stalled' && (
        <>
          {card.stalled_step && (
            <p className="task-card-stalled-reason muted">
              {t('teamKanban.stalledAt', { step: card.stalled_step })}
            </p>
          )}
          <StalledTaskActions taskId={card.task_id} />
        </>
      )}
    </li>
  )
}
