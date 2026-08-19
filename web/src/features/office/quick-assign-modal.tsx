// Giao việc without leaving the observation deck.
//
// Deliberately NOT a second composer: it renders the chat hub's AssignComposer inside a
// dialog, so the intent parsing, the staff roster, the SPRINT badge and the preview step
// are literally the same code. The office contributes only the overlay and the
// close-on-Escape behavior a dialog owes its user.
import { useEffect, useRef } from 'react'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import { AssignComposer } from '../../views/office-unified/assign-composer'

interface QuickAssignModalProps {
  activeRoom: string | null
  onClose: () => void
  onTaskCreated: (taskId: string) => void
}

export function QuickAssignModal({ activeRoom, onClose, onTaskCreated }: QuickAssignModalProps) {
  const panel = useRef<HTMLDivElement>(null)

  // Escape closes, and focus moves into the panel on open — a dialog that traps the
  // reader's place on the page behind it would be worse than no shortcut at all.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const { t } = useLanguage()
  return (
    // The backdrop closes on a click that STARTED on it; a drag out of the panel (text
    // selection in the brief box) must not be read as a dismissal.
    <div
      className="office-modal-backdrop"
      data-testid="quick-assign-modal"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="card office-modal-panel" role="dialog" aria-modal="true"
        aria-label={t('office.quickAssign')} tabIndex={-1} ref={panel}
      >
        <header className="office-modal-head">
          <strong>{t('office.quickAssign')}</strong>
          <Button variant="chip" onClick={onClose}>{t('common.close')}</Button>
        </header>
        <AssignComposer activeRoom={activeRoom} onTaskCreated={onTaskCreated} />
      </div>
    </div>
  )
}
