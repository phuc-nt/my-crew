// v50: per-task cost + token breakdown (read-only). Lazily fetches /api/team-tasks/:id/cost on
// expand so the kanban board stays cheap; shows one row per step-attempt + a task total. Cost may
// be null (dry-run) → rendered as "—".
// v82: expand doubles as the card's detail view — it also fetches the routing decision
// (/route) and shows one "vì sao đi đường này" line, plus /metrics for wall-clock +
// step mix. Both best-effort: their failure never blocks the cost table.
import { useState } from 'react'
import { api } from '../api/client'
import { Button } from './ui/button'
import { useLanguage } from '../i18n/language-context'
import { formatCost } from '../labels'
import type { TeamTaskCostPayload, TeamTaskMetricsPayload, TeamTaskRoutePayload } from '../types'

export function TeamTaskCost({ taskId }: { taskId: string }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<TeamTaskCostPayload | null>(null)
  const [route, setRoute] = useState<TeamTaskRoutePayload | null>(null)
  const [metrics, setMetrics] = useState<TeamTaskMetricsPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next && !data && !loading) {
      setLoading(true)
      setError(null)
      api
        .getTeamTaskCost(taskId)
        .then(setData)
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false))
      api
        .getTeamTaskRoute(taskId)
        .then(setRoute)
        .catch(() => undefined)
      api
        .getTeamTaskMetrics(taskId)
        .then(setMetrics)
        .catch(() => undefined)
    }
  }

  return (
    <div className="team-task-cost">
      <Button variant="ghost" onClick={toggle}>
        {open ? '▾' : '▸'} {t('teamTaskCost.toggle')}
      </Button>
      {open && loading && <span className="muted">{t('teamTaskCost.loading')}</span>}
      {open && error && <span className="error">{t('teamTaskCost.errorPrefix', { message: error })}</span>}
      {open && data && (
        <div className="team-task-cost-body">
          {(route?.mode === 'sprint' || route?.mode === 'team') && (
            <p className="muted team-task-route">
              {t('teamTaskRoute.line', {
                mode: route.mode.toUpperCase(),
                reason: route.reason || t('teamTaskRoute.noReason'),
              })}
            </p>
          )}
          {metrics && metrics.step_count > 0 && (
            <p className="muted team-task-metrics">
              {t('teamTaskMetrics.line', {
                wall: metrics.wall_clock_text,
                steps: metrics.step_count,
                content: metrics.content_steps,
                review: metrics.review_steps,
                rework: metrics.rework_steps,
              })}
            </p>
          )}
          <p className="muted">
            {t('teamTaskCost.total')}: <strong>{formatCost(data.total_cost_usd)}</strong> ·{' '}
            {data.total_input_tokens + data.total_output_tokens}{t('teamTaskCost.tokensSuffix')}
          </p>
          {data.steps.length === 0 ? (
            <p className="muted">{t('teamTaskCost.empty')}</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('teamTaskCost.colStep')}</th>
                  <th>{t('teamTaskCost.colEngine')}</th>
                  <th>{t('teamTaskCost.colCost')}</th>
                  <th>{t('teamTaskCost.colTokens')}</th>
                </tr>
              </thead>
              <tbody>
                {data.steps.map((s, i) => (
                  <tr key={`${s.step_id}-${i}`}>
                    <td>{s.step_id}</td>
                    <td>{s.engine}</td>
                    <td>{formatCost(s.cost_usd)}</td>
                    <td>
                      {s.input_tokens ?? 0}/{s.output_tokens ?? 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
