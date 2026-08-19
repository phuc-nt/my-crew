// The chat hub's third column: everything waiting on the CEO, across the whole fleet.
//
// The list itself is components/approvals-queue.tsx, shared with the work hub — this
// file is only the pane's chrome (title, count, aria label). Keeping the list in one
// place is what stops the two surfaces from disagreeing about what is pending.
import { ApprovalsQueue, usePendingCount } from '../../../components/approvals-queue'
import { useLanguage } from '../../../i18n/language-context'

export function PendingPane() {
  const { t } = useLanguage()
  const count = usePendingCount()

  return (
    <aside className="chat-pending" aria-label={t('pending.paneLabel')}>
      <p className="chat-pane-title">
        {t('pending.title')}
        {count > 0 && <span className="pending-count">{count}</span>}
      </p>
      <ApprovalsQueue />
    </aside>
  )
}
