// v50: per-task cost + token breakdown (read-only). Lazily fetches /api/team-tasks/:id/cost on
// expand so the kanban board stays cheap; shows one row per step-attempt + a task total. Cost may
// be null (dry-run) → rendered as "—".
import { useState } from 'react'
import { api } from '../api/client'
import { Button } from './ui/button'
import { useLanguage } from '../i18n/language-context'
import { formatCost } from '../labels'
import type { TeamTaskCostPayload } from '../types'

export function TeamTaskCost({ taskId }: { taskId: string }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<TeamTaskCostPayload | null>(null)
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
