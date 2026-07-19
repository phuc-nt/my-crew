// Two-step approve confirm (v9 P1 human-hoá): shows a plain-Vietnamese SUMMARY of the exact
// action the agent will run for real, with the destination flagged when it leaves the org.
// The raw (already-redacted) action JSON stays available in <details> as the source of truth —
// the summary never replaces it, and an unrecognised action falls back to a readable line, not
// a blank. Detail comes from the API, never constructed client-side. Modal: focus + Esc + scroll.
import { useEffect, useRef } from 'react'
import { summarizeAction } from '../action-summary'
import { Button } from './ui/button'
import type { ApprovalItem } from '../types'

export function ConfirmDialog({
  item,
  busy,
  onApprove,
  onCancel,
}: {
  item: ApprovalItem
  busy: boolean
  onApprove: () => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Modal a11y: focus + scroll the dialog into view (it renders at page end, off-screen on
    // a long list), and close on Esc.
    ref.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    ref.current?.focus?.()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onCancel])

  const summary = summarizeAction(item.action, item.reason)

  return (
    <div
      ref={ref}
      className="confirm-dialog"
      role="dialog"
      aria-modal="true"
      aria-label={`Duyệt việc ${item.id}`}
      tabIndex={-1}
    >
      <h3>Duyệt việc #{item.id}</h3>
      <p>Duyệt để agent thực hiện hành động này thật:</p>
      <p className={summary.external ? 'confirm-summary confirm-external' : 'confirm-summary'}>
        {summary.text}
      </p>
      {summary.external && (
        <p className="confirm-external-note">Hành động này gửi thông tin RA NGOÀI công ty.</p>
      )}
      <details className="action-detail-wrap">
        <summary>Chi tiết kỹ thuật</summary>
        <pre className="action-detail">{JSON.stringify(item.action, null, 2)}</pre>
      </details>
      <div className="confirm-actions">
        <Button variant="primary" disabled={busy} onClick={onApprove}>
          {busy ? 'Đang thực hiện…' : 'Duyệt & thực hiện'}
        </Button>{' '}
        <Button variant="ghost" disabled={busy} onClick={onCancel}>
          Huỷ
        </Button>
      </div>
    </div>
  )
}
