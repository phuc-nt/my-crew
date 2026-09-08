// v95: a step that died mid-answer still leaves something behind — the worker writes a
// fallback artifact with the failure and, when the graph got as far as drafting, the
// partial text. Instead of a bare red row, the thread shows that draft, why it stopped
// and one button to buy the step another attempt. Reads the same room artifact index
// as the todo strip, so the card leaves the thread the moment the retry is dispatched.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useRoomArtifacts, useStepArtifact } from '../../api/queries/use-artifact-queries'
import { queryKeys } from '../../api/queries/query-keys'
import { useRetryStalledStep } from '../../api/queries/use-work-queries'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import type { RoomArtifactStep, RoomArtifactTask } from '../../types'
import { CitationChips } from '../shared/citation-chips.tsx'
import { FailureGuidanceNote } from '../shared/failure-guidance-note'
import { OVERVIEW_ROOM_ID } from './chat-state'

/** The store's two dead-step statuses — exactly what the retry route accepts. */
const INTERRUPTED = new Set(['failed', 'timeout'])
const TASK_OVER = new Set(['done', 'cancelled'])

export function isInterrupted(status: string): boolean {
  return INTERRUPTED.has(status)
}

export interface InterruptedStep {
  task: RoomArtifactTask
  step: RoomArtifactStep
}

/** Dead steps of the room's live tasks. Exported for the unit test. */
export function interruptedSteps(tasks: readonly RoomArtifactTask[]): InterruptedStep[] {
  const out: InterruptedStep[] = []
  for (const task of tasks) {
    if (TASK_OVER.has(task.status)) continue
    for (const step of task.steps) if (isInterrupted(step.status)) out.push({ task, step })
  }
  return out
}

/** How much of the draft the card shows before the reader opens the full artifact. */
export const PARTIAL_PREVIEW_CHARS = 600

export function partialPreview(text: string): string {
  const trimmed = text.trim()
  return trimmed.length > PARTIAL_PREVIEW_CHARS
    ? `${trimmed.slice(0, PARTIAL_PREVIEW_CHARS).trimEnd()}…`
    : trimmed
}

function InterruptedAnswerCard({ roomId, task, step }: InterruptedStep & { roomId: string }) {
  const { t } = useLanguage()
  const qc = useQueryClient()
  // seq 0 = never dispatched, so there is no artifact to read.
  const artifact = useStepArtifact(task.task_id, step.seq > 0 ? step.seq : null)
  const retry = useRetryStalledStep()
  const [failure, setFailure] = useState<string | null>(null)

  const partial = artifact.data?.result_text?.trim() ?? ''
  const error = artifact.data?.error ?? ''
  const caseId = step.status === 'timeout' ? 'step_timeout' : 'step_failed'

  function onRetry() {
    setFailure(null)
    retry.mutate(
      { taskId: task.task_id, stepId: step.step_id, roomId },
      {
        onError: (err) => setFailure(err instanceof Error ? err.message : String(err)),
        // The next attempt overwrites this seq's artifact; forget the dead one.
        onSuccess: () =>
          void qc.invalidateQueries({
            queryKey: queryKeys.artifacts.step(task.task_id, step.seq),
          }),
      },
    )
  }

  return (
    <article className="interrupted-answer" data-testid="interrupted-answer">
      <p className="interrupted-answer-head">
        <span className="interrupted-answer-label">{t('interrupted.label')}</span>
        <span className="interrupted-answer-step">{step.title}</span>
        {step.assigned_to ? <span className="muted">@{step.assigned_to}</span> : null}
      </p>
      {partial ? (
        <>
          <pre className="interrupted-answer-partial">{partialPreview(partial)}</pre>
          <CitationChips text={partial} />
        </>
      ) : (
        <p className="muted interrupted-answer-none">
          {artifact.isLoading ? t('common.loading') : t('interrupted.noPartial')}
        </p>
      )}
      {error ? (
        <p className="interrupted-answer-error">
          <span className="failure-guide-label">{t('interrupted.errorLabel')}</span> {error}
        </p>
      ) : null}
      <FailureGuidanceNote caseId={caseId} />
      <div className="interrupted-answer-actions">
        <Button variant="primary" disabled={retry.isPending} onClick={onRetry}>
          {retry.isPending ? t('stalledActions.retrying') : t('interrupted.retry')}
        </Button>
        {failure ? (
          <span className="interrupted-answer-failure" role="alert">
            {t('stalledActions.retryFailed')} {failure}
          </span>
        ) : null}
      </div>
    </article>
  )
}

export function InterruptedAnswers({ roomId }: { roomId: string }) {
  const enabled = roomId !== OVERVIEW_ROOM_ID
  const { data } = useRoomArtifacts(roomId, enabled)
  const rows = interruptedSteps(data?.tasks ?? [])
  if (!enabled || rows.length === 0) return null
  return (
    <div className="interrupted-answers">
      {rows.map(({ task, step }) => (
        <InterruptedAnswerCard
          key={`${task.task_id}-${step.step_id}`}
          roomId={roomId}
          task={task}
          step={step}
        />
      ))}
    </div>
  )
}
