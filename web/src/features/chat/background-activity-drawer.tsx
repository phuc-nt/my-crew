// v95: "Hoạt động nền" — what the agents are doing right now, folded behind one line.
// The reducer keeps one live line per (task, step) from `step_activity` telemetry; this
// drawer counts them, says how many are subagents, and shows the newest line inline so
// the thread stays readable while a long step grinds through its tool calls.
import { useState } from 'react'
import { useLanguage } from '../../i18n/language-context'
import type { ActivityLine } from './chat-state'

/** deepagents' built-in delegation tool: a call to it means a subagent is working. */
export const SUBAGENT_TOOL = 'task'

export function isSubagentActivity(a: ActivityLine): boolean {
  return a.tool === SUBAGENT_TOOL
}

type Translate = ReturnType<typeof useLanguage>['t']

/** The one-line wording for a live activity. Exported for the unit test. */
export function activityText(a: ActivityLine, t: Translate): string {
  const step = a.step ?? ''
  if (isSubagentActivity(a)) {
    return t('backgroundActivity.subagentLine', { step, count: a.count ?? 0 })
  }
  if (a.phase === 'writing') return t('backgroundActivity.writingLine', { step })
  return t('chat.activityLine', { step, tool: a.tool ?? '', count: a.count ?? 0 })
}

export function BackgroundActivityDrawer({ activities }: { activities: readonly ActivityLine[] }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  if (activities.length === 0) return null
  const subagents = activities.filter(isSubagentActivity).length
  const latest = activities[activities.length - 1]
  return (
    <section className="background-activity" data-testid="background-activity">
      <button
        type="button"
        className="background-activity-head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="background-activity-title">{t('backgroundActivity.title')}</span>
        <span className="background-activity-count" data-testid="background-activity-count">
          {activities.length}
        </span>
        {subagents > 0 ? (
          <span className="background-activity-subagents" data-testid="background-activity-subagents">
            {t('backgroundActivity.subagents', { n: subagents })}
          </span>
        ) : null}
        {!open ? (
          <span className="background-activity-latest muted">{activityText(latest, t)}</span>
        ) : null}
        <span className="background-activity-chevron" aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open ? (
        <ul className="background-activity-list" aria-label={t('chat.activityLabel')}>
          {activities.map((a) => (
            <li
              key={`${a.task ?? ''} ${a.step ?? ''}`}
              className={`background-activity-item${isSubagentActivity(a) ? ' is-subagent' : ''}`}
            >
              {a.agent ? <span className="background-activity-agent">{a.agent}</span> : null}
              <span className="background-activity-text">{activityText(a, t)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
