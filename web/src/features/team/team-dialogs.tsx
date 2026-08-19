// The two destructive/irreversible-feeling confirms on the roster: removing an agent and
// applying a template upgrade. Both are deliberately two-step — the roster button opens
// the dialog, the dialog does the work — because both rewrite files under profiles/.
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { useLanguage } from '../../i18n/language-context'
import type { TemplateUpgradePreview } from '../../types'

export function DeleteAgentDialog({
  id, busy, onConfirm, onCancel,
}: {
  id: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useLanguage()
  return (
    <div
      className="confirm-dialog"
      role="dialog"
      aria-modal="true"
      aria-label={t('team.confirmDeleteAria')}
    >
      <h3>{t('team.confirmDeleteTitle', { id })}</h3>
      <p>{t('team.confirmDeleteBody')}</p>
      <Button variant="danger" disabled={busy} onClick={onConfirm}>
        {busy ? t('team.deleting') : t('team.delete')}
      </Button>{' '}
      <Button variant="ghost" disabled={busy} onClick={onCancel}>
        {t('common.cancel')}
      </Button>
    </div>
  )
}

export function TemplateUpgradeDialog({
  id, preview, busy, onApply, onCancel,
}: {
  id: string
  preview: TemplateUpgradePreview
  busy: boolean
  onApply: () => void
  onCancel: () => void
}) {
  const { t } = useLanguage()
  const applyFields = Object.keys(preview.apply)
  return (
    <div
      className="confirm-dialog"
      role="dialog"
      aria-modal="true"
      aria-label={t('team.aria.confirmUpgrade')}
    >
      <h3>
        {t('team.upgradeTitle', {
          id,
          from: preview.applied_version,
          to: preview.latest_version,
        })}
      </h3>
      {applyFields.length > 0 ? (
        <p>
          {t('team.upgradeWillApplyPrefix')}
          <strong>{applyFields.join(', ')}</strong>.
        </p>
      ) : (
        <EmptyState>{t('team.upgradeNoneToApply')}</EmptyState>
      )}
      {/* Fields the CEO edited by hand are listed as KEPT — an upgrade that silently
          overwrote them would make the badge something nobody dares click. */}
      {preview.keep.length > 0 && (
        <p className="muted">{t('team.upgradeKeep', { fields: preview.keep.join(', ') })}</p>
      )}
      <p className="muted">{t('team.upgradeBackupNote')}</p>
      <Button variant="ghost" disabled={busy} onClick={onApply}>
        {busy ? t('team.upgrading') : t('team.upgrade')}
      </Button>{' '}
      <Button variant="ghost" onClick={onCancel}>
        {t('common.cancel')}
      </Button>
    </div>
  )
}
