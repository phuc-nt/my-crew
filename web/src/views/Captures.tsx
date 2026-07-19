// Dual-lens P3: the Captures explorer (ADVANCED_NAV) — the maintainer's per-attempt
// telemetry table over the v26 captures store: engine tier, tokens, cost (+ whether it
// is exact or estimated), duration, error. Read-only; filter by task or agent; a row
// expands in place (no extra fetch — the list rows already carry every column).
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { formatCost } from '../labels'
import type { CaptureRow } from '../types'

function fmtCost(row: CaptureRow): string {
  if (row.cost_usd == null) return '—'
  return `${formatCost(row.cost_usd)} (${row.cost_source || '?'})`
}

function fmtTokens(row: CaptureRow): string {
  if (row.input_tokens == null && row.output_tokens == null) return '—'
  return `${row.input_tokens ?? 0}→${row.output_tokens ?? 0}`
}

export function Captures() {
  const { t } = useLanguage()
  const [searchParams, setSearchParams] = useSearchParams()
  const taskFilter = searchParams.get('task_id') ?? ''
  const [agentFilter, setAgentFilter] = useState('')
  const [rows, setRows] = useState<CaptureRow[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .getCaptures({
        task_id: taskFilter || undefined,
        agent: agentFilter || undefined,
        limit: 200,
      })
      .then((p) => setRows(p.captures))
      .catch(() => setRows([]))
  }, [taskFilter, agentFilter])
  useEffect(() => { load() }, [load])

  return (
    <section>
      {/* "Captures" stays literal English (a technical term, matching the rest of the codebase) —
          only the parenthetical suffix is translated. */}
      <PageHeader title={`Captures${t('captures.titleSuffix')}`} />
      <p className="ops-chat-hint">{t('captures.hint')}</p>
      <div className="captures-filters">
        {taskFilter && (
          <Button variant="chip" onClick={() => setSearchParams({})}>
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
              <th>{t('captures.colTime')}</th><th>{t('captures.colAgent')}</th>
              <th>{t('captures.colTaskStep')}</th><th>{t('captures.colEngine')}</th>
              <th>{t('captures.colTokens')}</th><th>{t('captures.colCost')}</th>
              <th>{t('captures.colDuration')}</th><th>{t('captures.colStatus')}</th>
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
                      attempt <code>{r.attempt_id}</code> · {t('captures.attemptType', { type: r.step_type })}
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
    </section>
  )
}

export default Captures
