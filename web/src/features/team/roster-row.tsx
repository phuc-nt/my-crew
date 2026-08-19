// One agent in the roster: identity, live state, and the two controls the CEO reaches
// for most (pause/resume, remove).
//
// The status overlay (budget, pending approvals) is its own query per row, so a roster of
// 11 agents fires 11 small requests that each fail independently — one dead agent blanks
// one cell instead of emptying the table.
import { Link } from 'react-router'
import { useAgentStatus } from '../../api/queries/use-team-queries'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import { KIND_LABEL, RUN_STATUS_LABEL, formatCost, labelFor } from '../../labels'
import type { AgentSummary, TemplateStatusRow } from '../../types'
import { useUiMode } from '../../ui-mode-context'
import { RunNowButton } from './run-now-button'

interface Props {
  agent: AgentSummary
  templateStatus?: TemplateStatusRow
  busy: boolean
  /** Set when a Resume flipped the registry but the profile still vetoes the agent. */
  profileVetoed: boolean
  onToggle: (agent: AgentSummary) => void
  onDelete: (id: string) => void
  onUpgrade: (id: string) => void
}

export function RosterRow({
  agent, templateStatus, busy, profileVetoed, onToggle, onDelete, onUpgrade,
}: Props) {
  const { t } = useLanguage()
  const { isHigh } = useUiMode()
  const { data: status } = useAgentStatus(agent.id)
  const ratio = status?.budget.ratio ?? 0

  return (
    <tr>
      <td data-label={t('team.colCode')}>
        <Link to={`/team/${agent.id}`}>{agent.id}</Link>
      </td>
      <td data-label={t('team.colName')}>
        {agent.name}
        {templateStatus?.upgradable && (
          <Button
            variant="ghost"
            className="template-upgrade-badge"
            title={t('team.templateUpgradeHint')}
            onClick={() => onUpgrade(agent.id)}
          >
            {t('team.templateUpgradeBadge', { version: templateStatus.latest_version })}
          </Button>
        )}
      </td>
      <td data-label={t('team.colState')}>
        {agent.enabled ? t('team.enabled') : t('team.disabled')}
        {profileVetoed && (
          <div className="error health-detail">{t('team.profileDisabledNotice')}</div>
        )}
      </td>
      <td data-label={t('team.colLastRun')}>
        {agent.last_run
          ? `${labelFor(KIND_LABEL, agent.last_run.kind, t)} · ${labelFor(RUN_STATUS_LABEL, agent.last_run.status, t)}`
          : t('team.neverRun')}
      </td>
      <td data-label={t('team.colBudget')}>
        <div className="budget-cell">
          <span>
            {status ? `${formatCost(status.budget.spent)} / ${formatCost(status.budget.cap)}` : '…'}
          </span>
          {/* High mode only: a pure-CSS usage bar, amber past 80% and red past the cap. */}
          {isHigh && status && (
            <div className="budget-bar" title={t('team.budgetRatioTitle', { pct: Math.round(ratio * 100) })}>
              <span
                className={
                  ratio >= 1 ? 'budget-bar-fill over'
                    : ratio >= 0.8 ? 'budget-bar-fill warn' : 'budget-bar-fill'
                }
                style={{ width: `${Math.min(100, ratio * 100)}%` }}
              />
            </div>
          )}
        </div>
      </td>
      <td data-label={t('team.colPendingApprovals')}>{status ? status.pending_approvals : '…'}</td>
      <td className="roster-actions">
        <RunNowButton agent={agent} />{' '}
        <Button variant="ghost" disabled={busy} onClick={() => onToggle(agent)}>
          {agent.enabled ? t('team.pause') : t('team.resume')}
        </Button>{' '}
        {/* The `default` agent has no Remove: the backend 400s it, so offering the button
            would only ever produce an error toast. */}
        {agent.id !== 'default' && (
          <Button variant="danger" disabled={busy} onClick={() => onDelete(agent.id)}>
            {t('team.delete')}
          </Button>
        )}
      </td>
    </tr>
  )
}
