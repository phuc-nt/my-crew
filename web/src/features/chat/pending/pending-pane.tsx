// The chat hub's third column: everything waiting on the CEO, across the whole fleet.
//
// Reads the same two query keys the Duyệt page reads, so answering here updates there
// (and vice versa) with no cross-component wiring — see use-approvals-queries.ts. New
// items arrive via the SSE→invalidate bridge, so nothing here polls.
import { useApprovalDecision, usePendingApprovals } from '../../../api/queries/use-approvals-queries'
import { useAnswerClarify, usePendingClarify } from '../../../api/queries/use-clarify-queries'
import { useLanguage } from '../../../i18n/language-context'
import { buildPendingQueue, type PendingEntry } from './pending-queue'
import { QuestionCard } from './question-card'

function ApprovalCard({ entry }: { entry: PendingEntry }) {
  const { t } = useLanguage()
  const decide = useApprovalDecision()
  const a = entry.approval
  if (!a) return null

  return (
    <li className="pending-card">
      <p className="pending-card-head">
        <span className="pending-agent">{a.agent_id}</span>
        <span className="pending-kind">{t('pending.approvalKind')}</span>
      </p>
      <p className="pending-reason">{a.reason}</p>
      <div className="pending-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ agentId: a.agent_id, approvalId: a.id, decision: 'approve' })}
        >
          {t('pending.approve')}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ agentId: a.agent_id, approvalId: a.id, decision: 'reject' })}
        >
          {t('pending.reject')}
        </button>
      </div>
      {decide.isError && <p className="error">{t('pending.decisionFailed')}</p>}
    </li>
  )
}

export function PendingPane() {
  const { t } = useLanguage()
  const approvals = usePendingApprovals()
  const clarify = usePendingClarify()
  const answer = useAnswerClarify()

  const queue = buildPendingQueue(
    approvals.data?.pending ?? [],
    clarify.data?.questions ?? [],
  )

  return (
    <aside className="chat-pending" aria-label={t('pending.paneLabel')}>
      <p className="chat-pane-title">
        {t('pending.title')}
        {queue.length > 0 && <span className="pending-count">{queue.length}</span>}
      </p>
      {queue.length === 0 ? (
        <p className="muted pending-empty">{t('pending.empty')}</p>
      ) : (
        <ul className="pending-list">
          {queue.map((entry) =>
            entry.kind === 'approval' ? (
              <ApprovalCard key={entry.key} entry={entry} />
            ) : (
              <QuestionCard key={entry.key} entry={entry} answer={answer} />
            ),
          )}
        </ul>
      )}
    </aside>
  )
}
