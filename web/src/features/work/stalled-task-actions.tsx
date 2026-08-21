// One-click unstick: Retry / Accept / Drop for a stalled task's dead step, plus
// Cancel for any live task — the button cluster the Work board and task detail page
// both need so a stuck task never has to detour through the coordinator chat.
//
// Shared here (not duplicated per surface) because the mutation + confirm-dialog +
// double-fire guard wiring is identical on both — same shape as `DeleteAgentDialog`'s
// two-step confirm (team-dialogs.tsx): the button opens the dialog, the dialog does
// the work. Drop/cancel are DESTRUCTIVE (lose a step's/task's in-flight work), so both
// get the confirm; retry/accept are reversible-in-spirit (retry just buys another
// attempt, accept only finalizes what already exists) and fire immediately.
import { useState } from 'react'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import {
  useAcceptStalledResult,
  useCancelTeamTask,
  useDropStalledStep,
  useRetryStalledStep,
} from '../../api/queries/use-work-queries'

interface ConfirmDialogProps {
  titleKey: string
  bodyKey: string
  confirmLabelKey: string
  busyLabelKey: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Same `.confirm-dialog` shell `DeleteAgentDialog` uses — a destructive action gets
 *  a second tap, not a first-click commit. */
function ConfirmDialog({
  titleKey, bodyKey, confirmLabelKey, busyLabelKey, busy, onConfirm, onCancel,
}: ConfirmDialogProps) {
  const { t } = useLanguage()
  return (
    <div className="confirm-dialog" role="dialog" aria-modal="true" aria-label={t(titleKey)}>
      <h3>{t(titleKey)}</h3>
      <p>{t(bodyKey)}</p>
      <Button variant="danger" disabled={busy} onClick={onConfirm}>
        {busy ? t(busyLabelKey) : t(confirmLabelKey)}
      </Button>{' '}
      <Button variant="ghost" disabled={busy} onClick={onCancel}>
        {t('common.cancel')}
      </Button>
    </div>
  )
}

type PendingConfirm = 'drop' | 'cancel' | null

/**
 * The action cluster for one stalled/live task. `taskId` + `stepId` (the dead step,
 * when known — absent for a review-exhausted stall, which `accept` still handles)
 * drive every button; `onError` lets the host surface the ops layer's verbatim
 * ValueError (never retried automatically — the risk note in phase-03's plan).
 */
export function StalledTaskActions({
  taskId, stepId, roomId, onError, showRecovery = true,
}: {
  taskId: string
  stepId?: string
  // The room this task lives in, when the host knows it (task-detail page). Passed
  // through to the mutations so their invalidation also refreshes that room's
  // artifacts — the detail page's actual render source. The board card omits it (its
  // board query already repaints), so it stays optional.
  roomId?: string
  onError?: (message: string) => void
  // Retry/Accept/Drop only make sense on a STALLED task — on a healthy open/running
  // task the ops layer rejects them with a 409. The host gates them off there and
  // still gets Cancel (valid on any live task). Defaults true so the stalled-only
  // callers (board card) need no change.
  showRecovery?: boolean
}) {
  const { t } = useLanguage()
  const retry = useRetryStalledStep()
  const accept = useAcceptStalledResult()
  const drop = useDropStalledStep()
  const cancel = useCancelTeamTask()
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm>(null)

  // A step id is required by the retry/accept/drop URLs even though the ops layer
  // derives the actual target step from task state (routes_team_task_actions.py) —
  // fall back to a stable placeholder so the buttons still render for a
  // review-exhausted stall (no dead step, `stepId` absent).
  const effectiveStepId = stepId || '_'
  const anyPending = retry.isPending || accept.isPending || drop.isPending || cancel.isPending

  function report(err: unknown, fallbackKey: string) {
    onError?.(err instanceof Error ? err.message : t(fallbackKey))
  }

  function runRetry() {
    retry.mutate(
      { taskId, stepId: effectiveStepId, roomId },
      { onError: (err) => report(err, 'stalledActions.retryFailed') },
    )
  }

  function runAccept() {
    accept.mutate(
      { taskId, stepId: effectiveStepId, roomId },
      { onError: (err) => report(err, 'stalledActions.acceptFailed') },
    )
  }

  function confirmDrop() {
    drop.mutate(
      { taskId, stepId: effectiveStepId, roomId },
      {
        onSuccess: () => setPendingConfirm(null),
        onError: (err) => {
          report(err, 'stalledActions.dropFailed')
          setPendingConfirm(null)
        },
      },
    )
  }

  function confirmCancel() {
    cancel.mutate({ taskId, roomId }, {
      onSuccess: () => setPendingConfirm(null),
      onError: (err) => {
        report(err, 'stalledActions.cancelFailed')
        setPendingConfirm(null)
      },
    })
  }

  return (
    <div className="stalled-task-actions">
      <div className="pending-actions">
        {showRecovery && (
          <>
            <Button variant="primary" disabled={anyPending} onClick={runRetry}>
              {retry.isPending ? t('stalledActions.retrying') : t('stalledActions.retry')}
            </Button>
            <Button variant="ghost" disabled={anyPending} onClick={runAccept}>
              {accept.isPending ? t('stalledActions.accepting') : t('stalledActions.accept')}
            </Button>
            <Button variant="danger" disabled={anyPending} onClick={() => setPendingConfirm('drop')}>
              {t('stalledActions.drop')}
            </Button>
          </>
        )}
        <Button variant="danger" disabled={anyPending} onClick={() => setPendingConfirm('cancel')}>
          {t('stalledActions.cancel')}
        </Button>
      </div>

      {pendingConfirm === 'drop' && (
        <ConfirmDialog
          titleKey="stalledActions.confirmDropTitle"
          bodyKey="stalledActions.confirmDropBody"
          confirmLabelKey="stalledActions.drop"
          busyLabelKey="stalledActions.dropping"
          busy={drop.isPending}
          onConfirm={confirmDrop}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
      {pendingConfirm === 'cancel' && (
        <ConfirmDialog
          titleKey="stalledActions.confirmCancelTitle"
          bodyKey="stalledActions.confirmCancelBody"
          confirmLabelKey="stalledActions.cancel"
          busyLabelKey="stalledActions.cancelling"
          busy={cancel.isPending}
          onConfirm={confirmCancel}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}
