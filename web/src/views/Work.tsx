// v7 M20: "Việc" — the one action page the CEO needs daily. Two blocks on one page:
// "Cần bạn duyệt" (pending Lớp B approvals across ALL agents, two-step confirm → approve/
// reject) on top, and "Việc đã giao" (the M15b assigned-tasks board) below. No new backend:
// approvals fan out client-side (usePendingApprovals), tasks reuse the existing board.
import { useCallback, useState } from 'react'
import { api } from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { type AgentApproval, usePendingApprovals } from '../hooks/use-pending-approvals'
import { Tasks } from './Tasks'

export function Work() {
  const { items, loading, error, refresh } = usePendingApprovals()
  const [confirming, setConfirming] = useState<AgentApproval | null>(null)
  const [busy, setBusy] = useState(false)
  const [opError, setOpError] = useState<string | null>(null)

  const act = useCallback(
    async (item: AgentApproval, kind: 'approve' | 'reject') => {
      setBusy(true)
      setOpError(null)
      try {
        if (kind === 'approve') await api.approve(item.agentId, item.id)
        else await api.reject(item.agentId, item.id)
        setConfirming(null)
        await refresh()
      } catch (e: unknown) {
        setOpError(e instanceof Error ? e.message : 'thao tác thất bại')
      } finally {
        setBusy(false)
      }
    },
    [refresh],
  )

  return (
    <section className="work-page">
      <h2>Việc</h2>

      <section className="work-approvals">
        <h3>Cần bạn duyệt {items.length > 0 && <span className="badge">{items.length}</span>}</h3>
        {error && <p className="error">Lỗi: {error}</p>}
        {loading ? (
          <p>Đang tải…</p>
        ) : items.length === 0 ? (
          <p className="muted">Không có việc nào chờ duyệt. 🎉</p>
        ) : (
          <ul className="approval-list">
            {items.map((it) => (
              <li key={`${it.agentId}-${it.id}`}>
                <div>
                  <strong>{it.agentId}</strong> · {it.reason}
                  <span className="muted"> · {it.created_at}</span>
                </div>
                <div className="agent-actions">
                  <button type="button" onClick={() => setConfirming(it)}>
                    Xem &amp; duyệt
                  </button>
                  <button
                    type="button"
                    className="danger"
                    disabled={busy}
                    onClick={() => void act(it, 'reject')}
                  >
                    Từ chối
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {opError && <p className="error">{opError}</p>}
      </section>

      <section className="work-tasks">
        <h3>Việc đã giao</h3>
        <Tasks />
      </section>

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
