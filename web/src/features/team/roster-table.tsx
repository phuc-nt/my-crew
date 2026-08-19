// The roster table. Owns the per-row action state (which row is busy, which row is asking
// to be deleted, which Resume was vetoed by a profile) so `team-page` stays a layout.
import { useState } from 'react'
import { api } from '../../api/client'
import { useAgents } from '../../api/queries/use-agents-queries'
import {
  useApplyTemplateUpgrade,
  useDeleteAgent,
  useSetAgentEnabled,
  useTemplateStatus,
} from '../../api/queries/use-team-queries'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import type { AgentSummary, TemplateUpgradePreview } from '../../types'
import { RosterRow } from './roster-row'
import { DeleteAgentDialog, TemplateUpgradeDialog } from './team-dialogs'

export function RosterTable({
  onError, onNote,
}: {
  onError: (message: string | null) => void
  onNote: (message: string) => void
}) {
  const { t } = useLanguage()
  const { data: agents, isLoading, isError } = useAgents()
  const { data: templateStatus } = useTemplateStatus()
  const setEnabled = useSetAgentEnabled()
  const del = useDeleteAgent()
  const upgrade = useApplyTemplateUpgrade()
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  // agent id → "the registry says enabled but the profile still vetoes it"
  const [vetoed, setVetoed] = useState<Record<string, boolean>>({})
  const [upgradeTarget, setUpgradeTarget] = useState<
    { id: string; preview: TemplateUpgradePreview } | null
  >(null)

  const statusById = Object.fromEntries((templateStatus?.agents ?? []).map((r) => [r.agent_id, r]))

  async function toggle(agent: AgentSummary) {
    setBusyId(agent.id)
    onError(null)
    try {
      // Don't trust the optimistic `enabled` alone: a Resume can flip the registry while
      // the profile still disables the agent, and the row has to say so or the button
      // looks broken.
      const res = await setEnabled.mutateAsync({ id: agent.id, enabled: !agent.enabled })
      setVetoed((prev) => {
        const next = { ...prev }
        if (res.enabled && !res.effective_enabled) next[agent.id] = true
        else delete next[agent.id]
        return next
      })
    } catch (e) {
      onError(e instanceof Error ? e.message : t('team.toggleFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function confirmDelete(id: string) {
    setBusyId(id)
    onError(null)
    try {
      await del.mutateAsync(id)
      setVetoed((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      setConfirmingDelete(null)
      onNote(t('team.deletedNote', { id }))
    } catch (e) {
      onError(e instanceof Error ? e.message : t('team.deleteFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function openUpgrade(id: string) {
    onError(null)
    try {
      setUpgradeTarget({ id, preview: await api.previewTemplateUpgrade(id) })
    } catch (e) {
      onError(e instanceof Error ? e.message : t('team.upgradePreviewFailed'))
    }
  }

  async function applyUpgrade(id: string) {
    setBusyId(id)
    onError(null)
    try {
      const res = await upgrade.mutateAsync(id)
      const n = Object.keys(res.apply).length
      onNote(
        n > 0
          ? t('team.upgradeAppliedNote', { id, n, backup: res.backup })
          : t('team.upgradeNoneNote', { id }),
      )
      setUpgradeTarget(null)
    } catch (e) {
      onError(e instanceof Error ? e.message : t('team.upgradeFailed'))
    } finally {
      setBusyId(null)
    }
  }

  if (isLoading) return <p>{t('common.loading')}</p>
  if (isError) return <p className="error">{t('team.loadAgentsFailed')}</p>
  if (!agents || agents.length === 0) return <EmptyState>{t('team.empty')}</EmptyState>

  return (
    <>
      <table className="agents-table">
        <thead>
          <tr>
            <th>{t('team.colCode')}</th>
            <th>{t('team.colName')}</th>
            <th>{t('team.colState')}</th>
            <th>{t('team.colLastRun')}</th>
            <th>{t('team.colBudget')}</th>
            <th>{t('team.colPendingApprovals')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <RosterRow
              key={a.id}
              agent={a}
              templateStatus={statusById[a.id]}
              busy={busyId === a.id}
              profileVetoed={Boolean(vetoed[a.id])}
              onToggle={(agent) => void toggle(agent)}
              onDelete={setConfirmingDelete}
              onUpgrade={(id) => void openUpgrade(id)}
            />
          ))}
        </tbody>
      </table>
      {confirmingDelete && (
        <DeleteAgentDialog
          id={confirmingDelete}
          busy={busyId === confirmingDelete}
          onConfirm={() => void confirmDelete(confirmingDelete)}
          onCancel={() => setConfirmingDelete(null)}
        />
      )}
      {upgradeTarget && (
        <TemplateUpgradeDialog
          id={upgradeTarget.id}
          preview={upgradeTarget.preview}
          busy={busyId === upgradeTarget.id}
          onApply={() => void applyUpgrade(upgradeTarget.id)}
          onCancel={() => setUpgradeTarget(null)}
        />
      )}
    </>
  )
}
