// One clarify question: option buttons for the common case, free text for the rest.
//
// Mirrors the Duyệt page's row (clarify-section.tsx) but drives the shared mutation, so
// an answer here refreshes both surfaces. A question answered elsewhere first (a
// Telegram tap) fails with a 409, which is not an error worth showing — the list
// refetches on settle and the row simply disappears.
import { useState } from 'react'
import type { useAnswerClarify } from '../../../api/queries/use-clarify-queries'
import { isAlreadyAnswered } from '../../../api/queries/use-clarify-queries'
import { useLanguage } from '../../../i18n/language-context'
import { isExpired, type PendingEntry } from './pending-queue'

interface QuestionCardProps {
  entry: PendingEntry
  answer: ReturnType<typeof useAnswerClarify>
}

export function QuestionCard({ entry, answer }: QuestionCardProps) {
  const { t } = useLanguage()
  const [text, setText] = useState('')
  const q = entry.question
  if (!q) return null

  // `new Date()` here and not in the pure module: expiry is a live comparison against
  // now, and the rule itself stays unit-tested with an injected timestamp.
  const expired = isExpired(q, new Date().toISOString())
  const send = (value: string) => {
    if (!value.trim() || expired) return
    answer.mutate({ id: q.id, answer: value })
    setText('')
  }

  return (
    <li className={`pending-card${expired ? ' is-expired' : ''}`}>
      <p className="pending-card-head">
        <span className="pending-agent">{q.agent_id}</span>
        <span className="pending-kind">{t('pending.questionKind')}</span>
      </p>
      <p className="pending-reason">{q.question}</p>
      {expired ? (
        <p className="muted">{t('pending.expired')}</p>
      ) : (
        <div className="pending-actions">
          {q.options.map((opt, i) => (
            <button
              key={`${q.id}-${i}`}
              type="button"
              className="btn btn-primary"
              disabled={answer.isPending}
              onClick={() => send(opt)}
            >
              {opt}
            </button>
          ))}
          <input
            className="pending-input"
            placeholder={t('pending.freeText')}
            value={text}
            disabled={answer.isPending}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send(text)
            }}
          />
        </div>
      )}
      {/* A race with Telegram is not a failure the CEO needs to see. */}
      {answer.isError && !isAlreadyAnswered(answer.error) && (
        <p className="error">{t('pending.answerFailed')}</p>
      )}
    </li>
  )
}
