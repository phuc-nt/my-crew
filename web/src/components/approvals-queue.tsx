// "Waiting on you" — the fleet's approvals + clarify questions as one time-ordered list.
//
// Shared verbatim by the chat hub's context pane and the work hub, because a queue that
// disagrees with itself across two screens is worse than no queue: both mount THIS
// component, which reads the two shared query keys, so a decision on either surface
// invalidates the same cache and repaints the other. There is no local copy of the list
// anywhere — that is the whole point of extracting it.
import { useState } from 'react'
import {
  useApprovalDecision,
  usePendingApprovals,
} from '../api/queries/use-approvals-queries'
import { useAnswerClarify, usePendingClarify } from '../api/queries/use-clarify-queries'
import { buildPendingQueue, type PendingEntry } from '../features/chat/pending/pending-queue'
import { QuestionCard } from '../features/chat/pending/question-card'
import { useLanguage } from '../i18n/language-context'
import type { ApprovalScope } from '../types'

function ApprovalCard({ entry }: { entry: PendingEntry }) {
  const { t } = useLanguage()
  const decide = useApprovalDecision()
  const a = entry.approval
  // Bounded NL enum, not free text: 'once' works for either button, 'always' only
  // makes sense paired with Approve, 'deny' only with Reject — the ops layer
  // (routes_ops_json.py) rejects anything outside {once, always, deny} with a 400.
  const [scope, setScope] = useState<ApprovalScope>('once')
  if (!a) return null

  return (
    <li className="pending-card">
      <p className="pending-card-head">
        <span className="pending-agent">{a.agent_id}</span>
        <span className="pending-kind">{t('pending.approvalKind')}</span>
      </p>
      <p className="pending-reason">{a.reason}</p>
      <label className="pending-scope">
        {t('pending.scopeLabel')}
        <select
          value={scope}
          disabled={decide.isPending}
          onChange={(e) => setScope(e.target.value as ApprovalScope)}
        >
          <option value="once">{t('pending.scopeOnce')}</option>
          <option value="always">{t('pending.scopeAlways')}</option>
          <option value="deny">{t('pending.scopeDeny')}</option>
        </select>
      </label>
      <div className="pending-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={decide.isPending || scope === 'deny'}
          onClick={() =>
            decide.mutate({ agentId: a.agent_id, approvalId: a.id, decision: 'approve', scope })
          }
        >
          {t('pending.approve')}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={decide.isPending || scope === 'always'}
          onClick={() =>
            decide.mutate({
              agentId: a.agent_id,
              approvalId: a.id,
              decision: 'reject',
              scope: scope === 'once' ? 'once' : 'deny',
            })
          }
        >
          {t('pending.reject')}
        </button>
      </div>
      {decide.isError && <p className="error">{t('pending.decisionFailed')}</p>}
    </li>
  )
}

/** The list itself, with no surrounding chrome — each hub supplies its own heading. */
export function ApprovalsQueue() {
  const { t } = useLanguage()
  const approvals = usePendingApprovals()
  const clarify = usePendingClarify()
  const answer = useAnswerClarify()

  const queue = buildPendingQueue(approvals.data?.pending ?? [], clarify.data?.questions ?? [])

  if (queue.length === 0) return <p className="muted pending-empty">{t('pending.empty')}</p>

  return (
    <ul className="pending-list">
      {queue.map((entry) =>
        entry.kind === 'approval' ? (
          <ApprovalCard key={entry.key} entry={entry} />
        ) : (
          <QuestionCard key={entry.key} entry={entry} answer={answer} />
        ),
      )}
    </ul>
  )
}

/** How many items the queue holds — the badge both hubs paint next to their heading. */
export function usePendingCount(): number {
  const approvals = usePendingApprovals()
  const clarify = usePendingClarify()
  return (approvals.data?.pending.length ?? 0) + (clarify.data?.questions.length ?? 0)
}
