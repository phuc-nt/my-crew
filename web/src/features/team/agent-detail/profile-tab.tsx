// Hồ sơ — who this agent is. Absorbs the old /overview view, which listed every agent in
// a table; here the same identity fields are shown for the ONE agent the route names,
// which is what the table was being scanned for anyway.
// v88 P4: name/model/model_chain/schedule became editable here (inline input +
// Save/Cancel via InlineEditRow) — the ≤3-click structured alternative to the raw YAML
// editor on the Advanced tab, which stays as the escape hatch for anything else.
import { useState } from 'react'
import {
  useAgentConfig,
  useAgentProfileSettings,
  useAgentSafety,
  usePatchAgentProfileSettings,
  useSetAgentDryRun,
} from '../../../api/queries/use-agent-detail-queries'
import { useAgents } from '../../../api/queries/use-agents-queries'
import { Badge } from '../../../components/ui/badge'
import { EmptyState } from '../../../components/ui/empty-state'
import { useLanguage } from '../../../i18n/language-context'
import { KIND_LABEL, RUN_STATUS_LABEL, labelFor } from '../../../labels'
import type { AgentStatus } from '../../../types'
import { InlineEditRow, useEditingField } from './inline-edit-row'
import { ModelField } from './model-field'
import { ScheduleField } from './schedule-field'

export function ProfileTab({ id, status }: { id: string; status: AgentStatus }) {
  const { t } = useLanguage()
  const { data: agents } = useAgents()
  const { data: config } = useAgentConfig(id)
  const summary = agents?.find((a) => a.id === id)
  const { data: safety } = useAgentSafety(id)
  const setDryRun = useSetAgentDryRun(id)
  const [dryRunError, setDryRunError] = useState<string | null>(null)

  const { data: settings } = useAgentProfileSettings(id)
  const patchSettings = usePatchAgentProfileSettings(id)
  const { editingField, setEditingField } = useEditingField()
  const [draftName, setDraftName] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)

  async function toggleDryRun() {
    if (!safety) return
    setDryRunError(null)
    try {
      await setDryRun.mutateAsync(!safety.dry_run)
    } catch (e) {
      setDryRunError(e instanceof Error ? e.message : t('agentDetail.dryRunToggleFailed'))
    }
  }

  async function saveName() {
    setFieldError(null)
    if (!draftName.trim()) {
      setFieldError(t('agentDetail.saveFailed'))
      return
    }
    try {
      await patchSettings.mutateAsync({ name: draftName })
      setEditingField(null)
    } catch (e) {
      setFieldError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
    }
  }

  return (
    <div className="agent-profile-tab">
      <dl className="agent-profile-facts">
        <dt>{t('agentDetail.fieldId')}</dt>
        <dd>{id}</dd>
        <InlineEditRow
          label={t('agentDetail.fieldName')}
          displayValue={status.name}
          editing={editingField === 'name'}
          onStartEdit={() => {
            setDraftName(settings?.name ?? status.name)
            setFieldError(null)
            setEditingField('name')
          }}
          onCancel={() => setEditingField(null)}
          onSave={saveName}
          busy={patchSettings.isPending}
          error={editingField === 'name' ? fieldError : null}
        >
          <input value={draftName} onChange={(e) => setDraftName(e.target.value)} />
        </InlineEditRow>
        <dt>{t('agentDetail.fieldState')}</dt>
        <dd>
          <Badge tone={status.enabled ? 'ok' : 'neutral'}>
            {status.enabled ? t('agentPage.enabled') : t('agentPage.disabled')}
          </Badge>
        </dd>
        <dt>{t('agentDetail.dryRunLabel')}</dt>
        <dd>
          {safety ? (
            <label className="agent-dry-run-toggle" title={t('agentDetail.dryRunHint')}>
              <input
                type="checkbox"
                checked={safety.dry_run}
                disabled={setDryRun.isPending}
                onChange={() => void toggleDryRun()}
              />
              <Badge tone={safety.dry_run ? 'warn' : 'accent'}>
                {safety.dry_run ? t('agentDetail.dryRunOn') : t('agentDetail.dryRunOff')}
              </Badge>
              <span className="agent-dry-run-source">
                (
                {safety.dry_run_source === 'profile'
                  ? t('agentDetail.dryRunSourceProfile')
                  : t('agentDetail.dryRunSourceFleet')}
                )
              </span>
            </label>
          ) : (
            '—'
          )}
          {dryRunError && <p className="error">{dryRunError}</p>}
        </dd>
        <ModelField
          id={id}
          model={settings?.model ?? null}
          modelChain={settings?.model_chain ?? []}
          editingField={editingField}
          setEditingField={setEditingField}
        />
        <ScheduleField
          id={id}
          schedule={settings?.schedule ?? {}}
          editingField={editingField}
          setEditingField={setEditingField}
        />
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
