// v33 P4: "Đội đang hỏi bạn" — pending clarify questions on the Duyệt page. Option
// buttons answer in one click; a free-text row covers everything else. The backend is
// first-answer-wins (a Telegram tap may race a web click) — a 409 here just means the
// question was already handled elsewhere, so the list refreshes instead of erroring.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { useLanguage } from '../i18n/language-context'
import type { ClarifyQuestion } from '../types'

function QuestionRow({ q, onDone }: { q: ClarifyQuestion; onDone: () => void }) {
  const { t } = useLanguage()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = (answer: string) => {
    if (!answer.trim()) return
    setBusy(true)
    setError(null)
    api
      .answerClarify(q.id, answer)
      .then(onDone)
      .catch((e: unknown) => {
        // 409 = answered elsewhere (Telegram) — refresh, not an error worth showing.
        // NOTE: this substring check matches the backend's own error text (data, not FE
        // copy) — it must stay as the literal Vietnamese the API returns, regardless of UI language.
        const msg = e instanceof Error ? e.message : t('clarify.sendFailed')
        if (msg.includes('đã được trả lời')) onDone()
        else setError(msg)
      })
      .finally(() => setBusy(false))
  }

  return (
    <li className="clarify-row">
      <div>
        <strong>{q.agent_id}</strong>{t('clarify.asks')}{q.question}
        {q.task_id && <span className="muted">{t('clarify.taskRef', { id: q.task_id.slice(0, 8) })}</span>}
      </div>
      <div className="clarify-actions">
        {q.options.map((opt, i) => (
          <Button
            key={`${q.id}-${i}`}
            variant="primary"
            disabled={busy}
            onClick={() => send(opt)}
          >
            {opt}
          </Button>
        ))}
        <input
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
    </li>
  )
}

export function ClarifySection() {
  const { t } = useLanguage()
  const [questions, setQuestions] = useState<ClarifyQuestion[]>([])

  const load = useCallback(() => {
    api
      .getClarifyPending()
      .then((res) => setQuestions(res.questions))
      .catch(() => setQuestions([]))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (questions.length === 0) return null
  return (
    <section className="clarify-section">
      <h3>
        {t('clarify.title')} <span className="badge">{questions.length}</span>
      </h3>
      <p className="muted">
        {t('clarify.hint')}
      </p>
      <ul className="clarify-list">
        {questions.map((q) => (
          <QuestionRow key={q.id} q={q} onDone={load} />
        ))}
      </ul>
    </section>
  )
}
