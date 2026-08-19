// Hồ sơ — who this agent is. Absorbs the old /overview view, which listed every agent in
// a table; here the same identity fields are shown for the ONE agent the route names,
// which is what the table was being scanned for anyway.
import { useAgents } from '../../../api/queries/use-agents-queries'
import { useAgentConfig } from '../../../api/queries/use-agent-detail-queries'
import { Badge } from '../../../components/ui/badge'
import { EmptyState } from '../../../components/ui/empty-state'
import { useLanguage } from '../../../i18n/language-context'
import { KIND_LABEL, RUN_STATUS_LABEL, labelFor } from '../../../labels'
import type { AgentStatus } from '../../../types'

export function ProfileTab({ id, status }: { id: string; status: AgentStatus }) {
  const { t } = useLanguage()
  const { data: agents } = useAgents()
  const { data: config } = useAgentConfig(id)
  const summary = agents?.find((a) => a.id === id)

  return (
    <div className="agent-profile-tab">
      <dl className="agent-profile-facts">
        <dt>{t('agentDetail.fieldId')}</dt>
        <dd>{id}</dd>
        <dt>{t('agentDetail.fieldName')}</dt>
        <dd>{status.name}</dd>
        <dt>{t('agentDetail.fieldState')}</dt>
        <dd>
          <Badge tone={status.enabled ? 'ok' : 'neutral'}>
            {status.enabled ? t('agentPage.enabled') : t('agentPage.disabled')}
          </Badge>
        </dd>
        <dt>{t('agentDetail.fieldTrust')}</dt>
        <dd>
          {status.trust_mode
            ? status.trust_mode === 'autonomous'
              ? t('agentPage.trustAutonomous')
              : t('agentPage.trustGuarded')
            : '—'}
        </dd>
        <dt>{t('agentDetail.fieldReports')}</dt>
        <dd>
          {summary?.report_kinds?.length
            ? summary.report_kinds.map((k) => labelFor(KIND_LABEL, k, t)).join(', ')
            : '—'}
        </dd>
        <dt>{t('agentDetail.fieldLastRun')}</dt>
        <dd>
          {status.last_run
            ? `${labelFor(KIND_LABEL, status.last_run.kind, t)} · ${labelFor(RUN_STATUS_LABEL, status.last_run.status, t)}`
            : t('team.neverRun')}
        </dd>
      </dl>
      <h4>{t('agentDetail.personaTitle')}</h4>
      {/* SOUL.md is the agent's persona; the editable form lives in the Kiến thức tab, so
          this is a read-only glance to answer "what did I tell this one to be?". */}
      {config?.files.soul ? (
        <pre className="agent-persona-preview">{config.files.soul.slice(0, 800)}</pre>
      ) : (
        <EmptyState>{t('agentDetail.personaEmpty')}</EmptyState>
      )}
    </div>
  )
}
