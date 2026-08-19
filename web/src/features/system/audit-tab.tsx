// Nhật ký & captures — per-attempt telemetry across the whole fleet: which engine ran,
// what it cost, how long, and whether it failed.
//
// The per-agent guardrail verdict log is NOT duplicated here — it is already the agent's
// own budget tab, and /api/audit only serves one agent at a time. This tab is the surface
// that has no per-agent home: every attempt, from every agent, in one table.
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'
import type { CaptureRow } from '../../types'

function fmtCost(row: CaptureRow): string {
  if (row.cost_usd == null) return '—'
  return `${formatCost(row.cost_usd)} (${row.cost_source || '?'})`
}

function fmtTokens(row: CaptureRow): string {
  if (row.input_tokens == null && row.output_tokens == null) return '—'
  return `${row.input_tokens ?? 0}→${row.output_tokens ?? 0}`
}

export function AuditTab() {
  const { t } = useLanguage()
  const [params, setParams] = useSearchParams()
  // task_id rides in the URL so a capture list stays linkable from a task; the agent box
  // is a local text filter and deliberately does not touch the query string.
  const taskFilter = params.get('task_id') ?? ''
  const [agentFilter, setAgentFilter] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data } = useQuery({
    queryKey: ['captures', taskFilter, agentFilter] as const,
    queryFn: () =>
      api.getCaptures({
        task_id: taskFilter || undefined,
        agent: agentFilter || undefined,
        limit: 200,
      }),
  })
  const rows = data?.captures ?? []

  return (
    <div>
      <p className="ops-chat-hint">{t('captures.hint')}</p>
      <div className="captures-filters">
        {taskFilter && (
          <Button
            variant="chip"
            onClick={() => {
              const next = new URLSearchParams(params)
              next.delete('task_id')
              setParams(next)
            }}
          >
            {t('captures.taskFilterChip', { task: taskFilter.slice(0, 12) })}
          </Button>
        )}
        <input
          placeholder={t('captures.agentFilterPlaceholder')}
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
        />
      </div>
      {rows.length === 0 ? (
        <EmptyState>{t('captures.empty')}</EmptyState>
      ) : (
        <table className="captures-table">
          <thead>
            <tr>
              <th>{t('captures.colTime')}</th>
              <th>{t('captures.colAgent')}</th>
              <th>{t('captures.colTaskStep')}</th>
              <th>{t('captures.colEngine')}</th>
              <th>{t('captures.colTokens')}</th>
              <th>{t('captures.colCost')}</th>
              <th>{t('captures.colDuration')}</th>
              <th>{t('captures.colStatus')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.attempt_id}
                onClick={() => setExpanded(expanded === r.attempt_id ? null : r.attempt_id)}
                className={expanded === r.attempt_id ? 'captures-row-open' : undefined}
              >
                <td>{r.ts?.slice(5, 16)}</td>
                <td>{r.agent_id}</td>
                <td title={`${r.task_id} / ${r.step_id}`}>
                  {r.task_id.slice(0, 8)}…/{r.step_id.slice(0, 10)}
                  {expanded === r.attempt_id && (
                    <div className="captures-detail">
                      attempt <code>{r.attempt_id}</code> ·{' '}
                      {t('captures.attemptType', { type: r.step_type })}
                      {r.review_round > 0 && t('captures.reviewRound', { n: r.review_round })}
                      {r.error && (
                        <div className="captures-error">
                          {t('captures.errorPrefix', { message: r.error })}
                        </div>
                      )}
                    </div>
                  )}
                </td>
                <td>{r.engine || '—'}</td>
                <td>{fmtTokens(r)}</td>
                <td>{fmtCost(r)}</td>
                <td>{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : '—'}</td>
                <td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
