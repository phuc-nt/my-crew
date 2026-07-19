// v54 P2: the office's left action rail — "Chờ anh/chị" (approvals + clarify merged, in
// place, 1-click) and "Sắp chạy" (fleet cron schedule, read-only). Reuses the EXISTING
// write paths only: api.approve/reject (same as Work.tsx, no confirm dialog here — the
// rail is the fast lane; the full two-step review stays on the Duyệt page) and
// api.answerClarify (same as clarify-section.tsx). No new backend write route.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { summarizeAction } from '../../action-summary'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { useLanguage } from '../../i18n/language-context'
import { formatDateTime } from '../../labels'
import { useSharedPendingApprovals } from '../../pending-approvals-context'
import type { AgentApproval } from '../../hooks/use-pending-approvals'
import type { ClarifyQuestion, ScheduleItem } from '../../types'

const CLARIFY_POLL_MS = 30_000 // same cadence as usePendingApprovals (v7 M20)
const SCHEDULE_POLL_MS = 60_000 // phase spec: refresh Sắp chạy every 60s

// A merged, ts-sortable rail item — either an approval or a clarify question. Keeping one
// literal union (rather than two side-by-side lists) makes the "sort by ts" requirement a
// single .sort() call instead of an interleave-merge.
type RailItem =
  | { kind: 'approval'; ts: string; approval: AgentApproval }
  | { kind: 'clarify'; ts: string; question: ClarifyQuestion }

function ApprovalCard({
  approval,
  busy,
  onApprove,
  onReject,
}: {
  approval: AgentApproval
  busy: boolean
  onApprove: () => void
  onReject: () => void
}) {
  const { t } = useLanguage()
  const summary = summarizeAction(approval.action, approval.reason, t)
  return (
    <Card className="office-rail-item">
      <div>
        <strong>{approval.agentId}</strong>
        <span className="muted"> · {formatDateTime(approval.created_at)}</span>
      </div>
      <p className={summary.external ? 'confirm-summary confirm-external' : 'confirm-summary'}>
        {summary.text}
      </p>
      <div className="office-rail-actions">
        <Button variant="primary" disabled={busy} onClick={onApprove}>
          {t('actionRail.approve')}
        </Button>
        <Button variant="danger" disabled={busy} onClick={onReject}>
          {t('actionRail.reject')}
        </Button>
      </div>
    </Card>
  )
}

function ClarifyCard({ question, onDone }: { question: ClarifyQuestion; onDone: () => void }) {
  const { t } = useLanguage()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = (answer: string) => {
    if (!answer.trim()) return
    setBusy(true)
    setError(null)
    api
      .answerClarify(question.id, answer)
      .then(onDone)
      .catch((e: unknown) => {
        // 409 = answered elsewhere (Telegram/Work page) — refresh silently, same posture
        // as clarify-section.tsx. This substring matches the backend's literal Vietnamese
        // error text (data, not FE copy) — must not be translated.
        const msg = e instanceof Error ? e.message : t('clarify.sendFailed')
        if (msg.includes('đã được trả lời')) onDone()
        else setError(msg)
      })
      .finally(() => setBusy(false))
  }

  return (
    <Card className="office-rail-item">
      <div>
        <strong>{question.agent_id}</strong>{t('clarify.asks')}{question.question}
      </div>
      <div className="office-rail-actions">
        {question.options.map((opt, i) => (
          <Button key={`${question.id}-${i}`} variant="primary" disabled={busy} onClick={() => send(opt)}>
            {opt}
          </Button>
        ))}
      </div>
      <div className="office-rail-actions">
        <input
          className="office-rail-input"
          placeholder={t('clarify.freeTextPlaceholder')}
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') send(text)
          }}
        />
        <Button variant="ghost" disabled={busy || !text.trim()} onClick={() => send(text)}>
          {t('clarify.send')}
        </Button>
      </div>
      {error && <p className="error">{error}</p>}
    </Card>
  )
}

function PendingQueue() {
  const { t } = useLanguage()
  const { items: approvals, refresh: refreshApprovals } = useSharedPendingApprovals()
  const [clarifyQuestions, setClarifyQuestions] = useState<ClarifyQuestion[]>([])
  const [busyApprovalId, setBusyApprovalId] = useState<number | null>(null)

  const loadClarify = useCallback(() => {
    api.getClarifyPending().then((res) => setClarifyQuestions(res.questions)).catch(() => undefined)
  }, [])

  useEffect(() => {
    loadClarify()
    const timer = setInterval(loadClarify, CLARIFY_POLL_MS)
    return () => clearInterval(timer)
  }, [loadClarify])

  const act = useCallback(
    async (approval: AgentApproval, action: 'approve' | 'reject') => {
      setBusyApprovalId(approval.id)
      try {
        if (action === 'approve') await api.approve(approval.agentId, approval.id)
        else await api.reject(approval.agentId, approval.id)
        await refreshApprovals()
      } finally {
        setBusyApprovalId(null)
      }
    },
    [refreshApprovals],
  )

  const items: RailItem[] = [
    ...approvals.map((approval): RailItem => ({ kind: 'approval', ts: approval.created_at, approval })),
    ...clarifyQuestions.map((question): RailItem => ({ kind: 'clarify', ts: question.asked_at, question })),
  ].sort((a, b) => a.ts.localeCompare(b.ts))

  return (
    <section className="office-rail-section">
      <h3>
        {t('actionRail.pendingTitle')}
        {items.length > 0 && <span className="badge">{items.length}</span>}
      </h3>
      {items.length === 0 ? (
        <p className="office-rail-empty">{t('actionRail.pendingEmpty')}</p>
      ) : (
        <div className="office-rail-list">
          {items.map((item) =>
            item.kind === 'approval' ? (
              <ApprovalCard
                key={`approval-${item.approval.agentId}-${item.approval.id}`}
                approval={item.approval}
                busy={busyApprovalId === item.approval.id}
                onApprove={() => void act(item.approval, 'approve')}
                onReject={() => void act(item.approval, 'reject')}
              />
            ) : (
              <ClarifyCard
                key={`clarify-${item.question.id}`}
                question={item.question}
                onDone={loadClarify}
              />
            ),
          )}
        </div>
      )}
    </section>
  )
}

function UpcomingSchedule() {
  const { t } = useLanguage()
  const [items, setItems] = useState<ScheduleItem[]>([])

  const load = useCallback(() => {
    api.getScheduleUpcoming().then((res) => setItems(res.items)).catch(() => undefined)
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, SCHEDULE_POLL_MS)
    return () => clearInterval(timer)
  }, [load])

  return (
    <section className="office-rail-section">
      <h3>{t('actionRail.upcomingTitle')}</h3>
      {items.length === 0 ? (
        <p className="office-rail-empty">{t('actionRail.upcomingEmpty')}</p>
      ) : (
        <ul className="office-rail-schedule">
          {items.map((item, i) => (
            <li key={`${item.agent_id}-${item.kind}-${i}`}>
              <span className="office-rail-schedule-time">{formatDateTime(item.next_ts)}</span>{' '}
              {item.label}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function ActionRail() {
  return (
    <aside className="office-rail">
      <PendingQueue />
      <UpcomingSchedule />
    </aside>
  )
}

export default ActionRail
