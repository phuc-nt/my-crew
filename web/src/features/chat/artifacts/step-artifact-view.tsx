// One step's produced text, with the recorder's log behind a 🔬 toggle.
//
// A step that produced nothing (a review step, for example) answers 404 — that is a
// normal outcome, not an error, so it reads as "no output" rather than a failure.
import { useState } from 'react'
import { useStepArtifact, useStepTranscript } from '../../../api/queries/use-artifact-queries'
import { useLanguage } from '../../../i18n/language-context'
import type { SelectedStep } from './artifact-drawer'
import { summarize, totalCost } from './transcript-presentation'

export function StepArtifactView({ step }: { step: SelectedStep }) {
  const { t } = useLanguage()
  const [showTranscript, setShowTranscript] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const artifact = useStepArtifact(step.taskId, step.seq)
  const transcript = useStepTranscript(step.taskId, step.seq, showTranscript)

  const events = transcript.data?.events ?? []

  return (
    <section className="artifact-detail" aria-label={step.title}>
      <header className="artifact-detail-head">
        <h4 className="artifact-detail-title">{artifact.data?.step_title ?? step.title}</h4>
        <button
          type="button"
          className="artifact-scope"
          aria-pressed={showTranscript}
          onClick={() => setShowTranscript((v) => !v)}
          title={t('artifacts.transcriptToggle')}
        >
          🔬
        </button>
      </header>

      {artifact.data?.self_check_failed ? (
        <p className="artifact-warning">{t('artifacts.selfCheckFailed')}</p>
      ) : null}

      {artifact.isLoading ? <p className="pending-empty">{t('common.loading')}</p> : null}
      {artifact.isError ? <p className="pending-empty">{t('artifacts.noOutput')}</p> : null}
      {artifact.data ? <pre className="artifact-text">{artifact.data.result_text}</pre> : null}

      {showTranscript ? (
        <div className="artifact-transcript">
          {transcript.isLoading ? <p className="pending-empty">{t('common.loading')}</p> : null}
          {transcript.isError ? <p className="pending-empty">{t('artifacts.noTranscript')}</p> : null}
          {transcript.data ? (
            <>
              <p className="artifact-transcript-meta">
                {t('artifacts.transcriptMeta', {
                  attempts: transcript.data.attempts,
                  events: events.length,
                  cost: totalCost(events).toFixed(4),
                })}
              </p>
              <ol className="artifact-event-list">
                {events.map((event, i) => {
                  const line = summarize(event)
                  return (
                    <li key={i} className="artifact-event">
                      <button
                        type="button"
                        className="artifact-event-line"
                        onClick={() => setExpanded((prev) => (prev === i ? null : i))}
                      >
                        <span className="artifact-event-kind">{line.kind}</span>
                        <span className="artifact-event-detail">{line.detail}</span>
                      </button>
                      {expanded === i ? <pre className="artifact-event-raw">{line.raw}</pre> : null}
                    </li>
                  )
                })}
              </ol>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
