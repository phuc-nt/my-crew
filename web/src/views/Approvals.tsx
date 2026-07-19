// Approvals ops view: list pending Lớp B proposals → two-step confirm (operator sees EXACTLY
// what posts) → approve (real gateway path) / reject. The confirm detail is the already-redacted
// pending action from the API (no separate confirm endpoint). React never builds/posts the
// action itself — it only triggers the existing approve endpoint.
import { useCallback, useState } from 'react'
import { useAgent } from '../agent-context'
import { summarizeAction } from '../action-summary'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/ui/empty-state'
import { api } from '../api/client'
import { formatDateTime } from '../labels'
import { useAgentData } from '../hooks/use-agent-data'
import type { ApprovalItem, ApprovalsPayload } from '../types'

export function Approvals() {
  const { selected } = useAgent()
  const get = useCallback((id: string) => api.getApprovals(id), [])
  const { data, loading, error } = useAgentData<ApprovalsPayload>(get)
  const [confirming, setConfirming] = useState<ApprovalItem | null>(null)
  const [pending, setPending] = useState<ApprovalItem[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [opError, setOpError] = useState<string | null>(null)

  const rows = pending ?? data?.pending ?? []

  async function run(fn: () => Promise<ApprovalsPayload>) {
    setBusy(true)
    setOpError(null)
    try {
      const res = await fn()
      setPending(res.pending)
      setConfirming(null)
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'action failed')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p>Đang tải…</p>
  if (error) return <p className="error">Lỗi: {error}</p>

  return (
    <section>
      <h2>Việc chờ duyệt</h2>
      {opError && <p className="error">Lỗi: {opError}</p>}
      {rows.length === 0 ? (
        <EmptyState>Không có việc nào chờ duyệt.</EmptyState>
      ) : (
        <table className="proposals-table">
          <thead>
            <tr>
              <th>Mã</th>
              <th>Hành động</th>
              <th>Lý do</th>
              <th>Lúc</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td data-label="Mã">{p.id}</td>
                <td data-label="Hành động">{summarizeAction(p.action, p.reason).text}</td>
                <td data-label="Lý do">{p.reason}</td>
                <td data-label="Lúc">{formatDateTime(p.created_at)}</td>
                <td>
                  <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(p)}>
                    Xem &amp; duyệt
                  </button>{' '}
                  <button
                    type="button"
                    className="btn btn-danger"
                    disabled={busy}
                    onClick={() => {
                      if (selected && window.confirm('Từ chối việc này?'))
                        run(() => api.reject(selected, p.id))
                    }}
                  >
                    Từ chối
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {confirming && selected && (
        <ConfirmDialog
          item={confirming}
          busy={busy}
          onCancel={() => setConfirming(null)}
          onApprove={() => run(() => api.approve(selected, confirming.id))}
        />
      )}
    </section>
  )
}
