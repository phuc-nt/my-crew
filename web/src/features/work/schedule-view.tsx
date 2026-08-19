// "Sắp chạy" — the fleet's next cron fires, soonest first.
//
// The backend returns the top-N already sorted; this only renders it and says how far
// off each one is, because "in 20 minutes" answers the CEO's actual question and an ISO
// timestamp does not.
import { useScheduleUpcoming } from '../../api/queries/use-work-queries'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import { formatDateTime } from '../../labels'

/** Minutes from now until `iso`, or null when it is unparseable or already past. */
function minutesUntil(iso: string): number | null {
  const at = Date.parse(iso)
  if (Number.isNaN(at)) return null
  const mins = Math.round((at - Date.now()) / 60_000)
  return mins >= 0 ? mins : null
}

export function ScheduleView() {
  const { t } = useLanguage()
  const { data, isLoading, isError } = useScheduleUpcoming()
  const items = data?.items ?? []

  if (isLoading) return <p className="muted">{t('work.loading')}</p>
  if (isError) return <p className="error">{t('schedule.loadError')}</p>
  if (items.length === 0) return <EmptyState>{t('schedule.empty')}</EmptyState>

  return (
    <ul className="schedule-list">
      {items.map((it) => {
        const mins = minutesUntil(it.next_ts)
        return (
          <li key={`${it.agent_id}-${it.kind}-${it.next_ts}`} className="schedule-row">
            <span className="schedule-when">
              {mins === null
                ? t('schedule.due')
                : mins < 60
                  ? t('schedule.inMinutes', { n: mins })
                  : t('schedule.inHours', { n: Math.round(mins / 60) })}
            </span>
            <span className="schedule-what">
              <strong>{it.agent_id}</strong> · {it.label || it.kind}
            </span>
            <span className="muted">{formatDateTime(it.next_ts) || it.next_ts}</span>
          </li>
        )
      })}
    </ul>
  )
}
