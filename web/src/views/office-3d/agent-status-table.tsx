// 2D fallback for the 3D office scene: a plain table (agent / trạng thái / công việc), rendered
// instead of the Canvas when prefers-reduced-motion is set or the UA looks mobile (see
// use-3d-fallback.ts). No animation — just the same derived desk-state map as a static list.
import { EmptyState } from '../../components/ui/empty-state'
import { DICT } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'
import type { UiKey } from '../../i18n/dictionary'
import type { AgentDeskState, AgentState } from './agent-office-state'

const STATE_LABEL_KEY: Record<AgentState, UiKey> = {
  idle: 'agentStatusTable.stateIdle',
  assigned: 'agentStatusTable.stateAssigned',
  working: 'agentStatusTable.stateWorking',
  done: 'agentStatusTable.stateDone',
  error: 'agentStatusTable.stateError',
}

interface AgentStatusTableProps {
  agentIds: string[]
  desks: Map<string, AgentDeskState>
  // v32 parity with the 3D desks: a row click opens the same target a desk click does.
  onDeskSelect?: (id: string) => void
  // Dual-lens P1 parity with the 3D 🔒 badge (high-mode only — parent gates it).
  needsShellAgents?: Set<string>
}

// Verdict cell parity with the 3D flash ring — persistent text here (a static table
// cannot flash): "✓ đạt" or "✗ N lỗi". Uses DICT.vi directly (exported pure function,
// called from tests without a component/hook context) — mirrors the 3D pill's default.
export function verdictCellText(desk: AgentDeskState | undefined): string {
  const v = desk?.lastVerdict
  if (!v) return '—'
  return v.verdict === 'passed'
    ? DICT.vi['agentStatusTable.verdictPassed']
    : DICT.vi['agentStatusTable.verdictFailed'].replaceAll('{n}', String(v.failureCount))
}

export function AgentStatusTable({
  agentIds, desks, onDeskSelect, needsShellAgents,
}: AgentStatusTableProps) {
  const { t } = useLanguage()
  return (
    <section className="office-3d-scene">
      {/* v37: h3 not h2 — this is a subsection of the Office page, whose own <h2>"Văn phòng"
          is the page title; two stacked h2s read as a duplicate title in the 2D fallback. */}
      <h3>{t('agentStatusTable.title')}</h3>
      <p className="ops-chat-hint">{t('agentStatusTable.hint')}</p>
      {agentIds.length === 0 ? (
        <EmptyState>{t('agentStatusTable.empty')}</EmptyState>
      ) : (
        <table className="office-3d-fallback-table">
          <thead>
            <tr>
              <th>{t('agentStatusTable.colStaff')}</th>
              <th>{t('agentStatusTable.colState')}</th>
              <th>{t('agentStatusTable.colTask')}</th>
              <th>{t('agentStatusTable.colStep')}</th>
              <th>{t('agentStatusTable.colVerdict')}</th>
            </tr>
          </thead>
          <tbody>
            {agentIds.map((id) => {
              const d = desks.get(id)
              const state: AgentState = d?.state ?? 'idle'
              return (
                <tr
                  key={id}
                  onClick={onDeskSelect ? () => onDeskSelect(id) : undefined}
                  style={onDeskSelect ? { cursor: 'pointer' } : undefined}
                  title={onDeskSelect ? t('agentStatusTable.clickToOpen') : undefined}
                >
                  <td data-label={t('agentStatusTable.colStaff')}>
                    {needsShellAgents?.has(id) ? '🔒 ' : ''}
                    {id}
                  </td>
                  <td data-label={t('agentStatusTable.colState')}>
                    <span className={`office-3d-state office-3d-state-${state}`}>
                      {t(STATE_LABEL_KEY[state])}
                    </span>
                  </td>
                  <td data-label={t('agentStatusTable.colTask')}>{d?.taskTitle ?? '—'}</td>
                  <td data-label={t('agentStatusTable.colStep')}>{d?.stepTitle ?? '—'}</td>
                  <td data-label={t('agentStatusTable.colVerdict')}>{verdictCellText(d)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
