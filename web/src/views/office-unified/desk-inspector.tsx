// Dual-lens P2 (high-mode only): click a desk → this drawer answers the maintainer's
// three questions without leaving the office — what is this agent doing (state/step/
// phase from the desk reducer), on which engine tier, and what has it cost so far.
// Fetch-on-open only (no background polling): agent status always; per-task cost only
// when the desk is PIC of a task (the only exact task_id the stream provides — see
// agent-office-state.ts picTasks).
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../../api/client'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import { formatCost } from '../../labels'
import type { AgentDeskState } from '../office-3d/agent-office-state'
import { deskTooltipText } from '../office-3d/agent-desk'
import type { AgentStatus, TeamTaskCostPayload } from '../../types'

interface DeskInspectorProps {
  agentId: string
  desk: AgentDeskState | undefined
  onClose: () => void
}

export function DeskInspector({ agentId, desk, onClose }: DeskInspectorProps) {
  const { t } = useLanguage()
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [cost, setCost] = useState<TeamTaskCostPayload | null>(null)
  const picTask = desk && desk.picTasks.size > 0 ? [...desk.picTasks][0] : null

  useEffect(() => {
    let stop = false
    api.getAgentStatus(agentId).then((s) => { if (!stop) setStatus(s) }).catch(() => undefined)
    if (picTask) {
      api.getTeamTaskCost(picTask).then((c) => { if (!stop) setCost(c) }).catch(() => undefined)
    }
    return () => { stop = true }
  }, [agentId, picTask])

  const engines = cost
    ? [...new Set(cost.steps.map((s) => s.engine).filter(Boolean))].join(', ')
    : null

  return (
    // v53: card padding/border/radius/shadow via .card; position:fixed etc stay on
    // .desk-inspector (Card only renders a <div>, so the class is applied directly here
    // to keep the semantic <aside> element).
    <aside className="card desk-inspector" aria-label={t('deskInspector.ariaLabel', { agentId })}>
      <header className="desk-inspector-head">
        <strong>{agentId}</strong>
        <Button variant="chip" onClick={onClose}>{t('common.close')}</Button>
      </header>
      {desk && (
        <p>
          {deskTooltipText(desk, t)}
          {desk.phase ? t('deskInspector.phase', { phase: desk.phase }) : ''}
        </p>
      )}
      {status && (
        <p className="muted">
          {status.trust_mode === 'guarded' ? 'guarded' : 'autonomous'} · {t('deskInspector.monthlyBudget')}:{' '}
          {formatCost(status.budget.spent)} / {formatCost(status.budget.cap)}
        </p>
      )}
      {picTask && (
        <div className="desk-inspector-task">
          <p>
            {t('deskInspector.picTask')}: <code>{picTask}</code>
            {engines && <> · engine: {engines}</>}
          </p>
          {cost && (
            <p>
              {t('deskInspector.taskCost')}: {formatCost(cost.total_cost_usd)} (
              {t('deskInspector.stepsCount', { n: cost.steps.length })})
            </p>
          )}
        </div>
      )}
      <p className="desk-inspector-links">
        <Link to={`/agents/${agentId}`}>{t('deskInspector.agentPage')}</Link>
        {picTask && (
          <>
            {' · '}
            <Link to={`/captures?task_id=${encodeURIComponent(picTask)}`}>
              {t('deskInspector.taskCaptures')}
            </Link>
          </>
        )}
      </p>
    </aside>
  )
}
