// v7 M20: "Việc" — the one action page the CEO needs daily. Two blocks on one page:
// "Cần bạn duyệt" (pending Lớp B approvals across ALL agents, two-step confirm → approve/
// reject) on top, and "Việc đã giao" (the M15b assigned-tasks board) below. No new backend:
// approvals fan out client-side (usePendingApprovals), tasks reuse the existing board.
import { useCallback, useState } from 'react'
import { api } from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { formatDateTime } from '../labels'
import { useAutoApproved } from '../hooks/use-auto-approved'
import { type AgentApproval, usePendingApprovals } from '../hooks/use-pending-approvals'
import { Tasks } from './Tasks'
import { ClarifySection } from './clarify-section'
import { TeamTaskKanban } from './team-task-kanban'

export function Work() {
  const { t } = useLanguage()
  const { items, loading, error, refresh } = usePendingApprovals()
  const { rows: autoApproved } = useAutoApproved()
  const [confirming, setConfirming] = useState<AgentApproval | null>(null)
  const [busy, setBusy] = useState(false)
  const [opError, setOpError] = useState<string | null>(null)

  const act = useCallback(
    async (item: AgentApproval, kind: 'approve' | 'reject') => {
      // Reject is safe + reversible (the agent can re-prepare), so it only needs a light
      // confirm to stop a mis-tap on mobile — not the full approve dialog (v9 P1 / red-team M2).
      if (kind === 'reject' && !window.confirm(t('work.rejectConfirm'))) return
      setBusy(true)
      setOpError(null)
      try {
        if (kind === 'approve') await api.approve(item.agentId, item.id)
        else await api.reject(item.agentId, item.id)
        setConfirming(null)
        await refresh()
      } catch (e: unknown) {
        setOpError(e instanceof Error ? e.message : t('work.opFailed'))
      } finally {
        setBusy(false)
      }
    },
    [refresh, t],
  )

  return (
    <section className="work-page">
      <PageHeader title={t('work.title')} />

      {/* v33 P4: clarify questions — the CEO's other inbox besides approvals. */}
      <ClarifySection />

      <section className="work-approvals">
        <h3>{t('work.pendingApprovalTitle')} {items.length > 0 && <span className="badge">{items.length}</span>}</h3>
        {error && <p className="error">{t('team.errorPrefix', { message: error })}</p>}
        {loading ? (
          <p>{t('work.loading')}</p>
        ) : items.length === 0 ? (
          <EmptyState>{t('work.emptyApprovals')}</EmptyState>
        ) : (
          <ul className="approval-list">
            {items.map((it) => (
              <li key={`${it.agentId}-${it.id}`}>
                <div>
                  <strong>{it.agentId}</strong> · {it.reason}
                  <span className="muted"> · {formatDateTime(it.created_at)}</span>
                </div>
                <div className="agent-actions">
                  <Button variant="primary" onClick={() => setConfirming(it)}>
                    {t('work.reviewAndApprove')}
                  </Button>
                  <Button
                    variant="danger"
                    disabled={busy}
                    onClick={() => void act(it, 'reject')}
                  >
                    {t('work.reject')}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {opError && <p className="error">{opError}</p>}
      </section>

      {/* v33 P3: team tasks as read-only kanban lanes — card click opens the workroom. */}
      <TeamTaskKanban />

      <section className="work-tasks">
        <h3>{t('work.assignedTasksTitle')}</h3>
        <Tasks />
      </section>

      {autoApproved.length > 0 && (
        <section className="work-auto-approved">
          <h3>{t('work.autoApprovedTitle', { n: autoApproved.length })}</h3>
          <p className="muted">
            {t('work.autoApprovedHint')}
          </p>
          <ul className="auto-approved-list">
            {autoApproved.map((r, i) => (
              <li key={`${r.agentId}-${i}`}>
                <strong>{r.agentId}</strong> · {t('work.autoApprovedReport', { kind: r.kind })}
                <span className="muted"> · {r.timestamp.slice(11, 16)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {confirming && (
        <ConfirmDialog
          item={confirming}
          busy={busy}
          onApprove={() => void act(confirming, 'approve')}
          onCancel={() => setConfirming(null)}
        />
      )}
    </section>
  )
}
