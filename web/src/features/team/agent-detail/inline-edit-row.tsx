// v88 P4: one editable "label: value [Sửa]" row — the shared shape every profile-settings
// field (name/model/model_chain/schedule/budget cap) uses so a config edit is display →
// click Edit → input + Save/Cancel → back to display, in one click to open and one to
// commit (≤3 total incl. picking the field). Kept tiny and dumb on purpose: the field-
// specific parse/format (e.g. model_chain's comma-list, schedule's multi-line map) lives
// in the caller, this component only owns the click-to-edit UI shell + busy/error display.
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from '../../../components/ui/button'
import { useLanguage } from '../../../i18n/language-context'

export function InlineEditRow({
  label,
  displayValue,
  helpText,
  editing,
  onStartEdit,
  onCancel,
  onSave,
  busy,
  error,
  children,
}: {
  label: string
  /** Read-mode text — the caller formats it (e.g. "(dùng model chung của công ty)" for empty). */
  displayValue: string
  helpText?: string
  editing: boolean
  onStartEdit: () => void
  onCancel: () => void
  onSave: () => void | Promise<void>
  busy: boolean
  error: string | null
  /** The edit-mode input(s) — owned by the caller so each field's shape (text/textarea/
   *  comma-list) stays field-specific instead of forcing one generic input type here. */
  children: ReactNode
}) {
  const { t } = useLanguage()
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {editing ? (
          <div className="inline-edit-row-form">
            {children}
            {helpText && <p className="muted">{helpText}</p>}
            <div className="agent-actions">
              <Button variant="primary" disabled={busy} onClick={() => void onSave()}>
                {busy ? t('agentKnowledge.saving') : t('agentDetail.saveBtn')}
              </Button>
              <Button variant="ghost" disabled={busy} onClick={onCancel}>
                {t('agentDetail.cancelBtn')}
              </Button>
            </div>
            {error && <p className="error">{error}</p>}
          </div>
        ) : (
          <span className="inline-edit-row-display">
            {displayValue}{' '}
            <Button variant="chip" onClick={onStartEdit}>
              {t('agentDetail.editBtn')}
            </Button>
          </span>
        )}
      </dd>
    </>
  )
}

/** True when `editing` is a specific field key equal to `key`. A small helper so each
 *  editable row in a tab can share one `editingField: string | null` piece of state
 *  instead of one boolean per field (which tab-level state would otherwise need). */
export function useEditingField() {
  const [editingField, setEditingField] = useState<string | null>(null)
  return { editingField, setEditingField }
}
