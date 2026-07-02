// Step 3 helper: day-of-week multi-select + a time picker → a 5-field cron string
// `m h * * dow` (e.g. "0 9 * * 1,3,5"). The generated string is also shown as plain text
// so the operator can verify exactly what will be scheduled before Create. Empty
// day-selection means "no schedule" (manual-only report kind) — the parent omits the
// kind from the schedule map entirely in that case.
import { useMemo, useState } from 'react'

const DAYS: { label: string; value: number }[] = [
  { label: 'Sun', value: 0 },
  { label: 'Mon', value: 1 },
  { label: 'Tue', value: 2 },
  { label: 'Wed', value: 3 },
  { label: 'Thu', value: 4 },
  { label: 'Fri', value: 5 },
  { label: 'Sat', value: 6 },
]

export function buildCron(time: string, days: number[]): string | null {
  if (days.length === 0) return null
  const [h, m] = time.split(':')
  const hour = Number(h)
  const minute = Number(m)
  if (Number.isNaN(hour) || Number.isNaN(minute)) return null
  const dow = [...days].sort((a, b) => a - b).join(',')
  return `${minute} ${hour} * * ${dow}`
}

export function ScheduleBuilder({
  kind,
  onChange,
}: {
  kind: string
  onChange: (cron: string | null) => void
}) {
  const [time, setTime] = useState('09:00')
  const [days, setDays] = useState<number[]>([])

  const cron = useMemo(() => buildCron(time, days), [time, days])

  function toggleDay(value: number) {
    const next = days.includes(value) ? days.filter((d) => d !== value) : [...days, value]
    setDays(next)
    onChange(buildCron(time, next))
  }

  function handleTime(next: string) {
    setTime(next)
    onChange(buildCron(next, days))
  }

  return (
    <div className="schedule-builder">
      <div className="schedule-builder-days">
        {DAYS.map((d) => (
          <label key={d.value}>
            <input
              type="checkbox"
              checked={days.includes(d.value)}
              onChange={() => toggleDay(d.value)}
            />{' '}
            {d.label}
          </label>
        ))}
      </div>
      <label>
        Time:{' '}
        <input
          type="time"
          value={time}
          onChange={(e) => handleTime(e.target.value)}
          aria-label={`${kind} schedule time`}
        />
      </label>
      <p className="muted schedule-builder-cron">
        cron: {cron ?? 'manual only (no days selected)'}
      </p>
    </div>
  )
}
