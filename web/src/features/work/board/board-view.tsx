// The task board: coordinator lanes, filterable by who owns the work.
//
// Filtering is client-side over the one board payload the backend already returns in a
// single call — a per-filter request would buy nothing and would lose the SSE bridge's
// single invalidation point.
import { useMemo, useState } from 'react'
import { useTaskBoard } from '../../../api/queries/use-work-queries'
import { EmptyState } from '../../../components/ui/empty-state'
import type { UiKey } from '../../../i18n/dictionary'
import { useLanguage } from '../../../i18n/language-context'
import type { TeamBoardLane } from '../../../types'
import { TaskCard } from './task-card'

const LANE_LABEL_KEY: Record<string, UiKey> = {
  planning: 'teamKanban.lanePlanning',
  open: 'teamKanban.laneOpen',
  running: 'teamKanban.laneRunning',
  done: 'teamKanban.laneDone',
  khac: 'teamKanban.laneStuck',
}

/**
 * How many finished tasks the done lane shows before it stops.
 *
 * Measured on the real fleet: `done` held 110 of the board's 115 cards, which rendered a
 * 16,000px page whose only live lanes were pushed off the top. Finished work is history
 * — the outputs tab is where it belongs — so the lane keeps the most recent slice and
 * says how many it left out.
 */
const DONE_LIMIT = 10

/** Keep every lane (an empty lane is information: nothing is running), filter the cards. */
function filterLanes(lanes: readonly TeamBoardLane[], pic: string): TeamBoardLane[] {
  return lanes.map((lane) => {
    const cards = pic ? lane.cards.filter((c) => c.pic_id === pic) : lane.cards
    return { ...lane, cards }
  })
}

export function BoardView() {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useTaskBoard()
  const [pic, setPic] = useState('')

  const lanes = data?.lanes ?? []
  // Owner options come from the board itself, so the filter only ever offers agents
  // that actually hold a task.
  const owners = useMemo(
    () => [...new Set(lanes.flatMap((l) => l.cards.map((c) => c.pic_id)).filter(Boolean))].sort(),
    [lanes],
  )
  const shown = useMemo(() => filterLanes(lanes, pic), [lanes, pic])
  const total = shown.reduce((n, l) => n + l.cards.length, 0)
  // What is still moving, which is the number the CEO actually acts on — a fleet with
  // 109 finished tasks and nothing running is idle, and one total would say "115".
  const live = shown
    .filter((l) => l.id !== 'done')
    .reduce((n, l) => n + l.cards.length, 0)

  if (isLoading) return <p className="muted">{t('work.loading')}</p>
  if (isError) return <p className="error">{t('teamKanban.loadError')}</p>

  return (
    <section className="task-board">
      <div className="board-filters">
        <label>
          {t('board.filterOwner')}{' '}
          <select value={pic} onChange={(e) => setPic(e.target.value)}>
            <option value="">{t('board.filterAll')}</option>
            {owners.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">{t('board.taskCount', { n: live, done: total - live })}</span>
      </div>

      {total === 0 ? (
        <EmptyState>{t('board.empty')}</EmptyState>
      ) : (
        <div className="board-lanes">
          {shown.map((lane) => {
            const capped = lane.id === 'done' ? lane.cards.slice(0, DONE_LIMIT) : lane.cards
            const hidden = lane.cards.length - capped.length
            return (
              <div key={lane.id} className={`board-lane lane-${lane.id}`}>
                <p className="board-lane-title">
                  {LANE_LABEL_KEY[lane.id] ? t(LANE_LABEL_KEY[lane.id]) : lane.id}{' '}
                  <span className="muted">({lane.cards.length})</span>
                </p>
                <ul className="board-lane-cards">
                  {capped.map((c) => (
                    <TaskCard key={c.task_id} card={c} lane={lane.id} />
                  ))}
                </ul>
                {hidden > 0 && <p className="muted board-lane-more">{t('board.moreDone', { n: hidden })}</p>}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
