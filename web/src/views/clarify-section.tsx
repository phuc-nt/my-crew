// v33 P4: "Đội đang hỏi bạn" — pending clarify questions on the Duyệt page. Option
// buttons answer in one click; a free-text row covers everything else. The backend is
// first-answer-wins (a Telegram tap may race a web click) — a 409 here just means the
// question was already handled elsewhere, so the list refreshes instead of erroring.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ClarifyQuestion } from '../types'

function QuestionRow({ q, onDone }: { q: ClarifyQuestion; onDone: () => void }) {
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
        const msg = e instanceof Error ? e.message : 'không gửi được câu trả lời'
        if (msg.includes('đã được trả lời')) onDone()
        else setError(msg)
      })
      .finally(() => setBusy(false))
  }

  return (
    <li className="clarify-row">
      <div>
        <strong>{q.agent_id}</strong> hỏi: {q.question}
        {q.task_id && <span className="muted"> · việc {q.task_id.slice(0, 8)}</span>}
      </div>
      <div className="clarify-actions">
        {q.options.map((opt, i) => (
          <button
            key={`${q.id}-${i}`}
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => send(opt)}
          >
            {opt}
          </button>
        ))}
        <input
          placeholder="hoặc trả lời chi tiết…"
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') send(text)
          }}
        />
        <button type="button" disabled={busy || !text.trim()} onClick={() => send(text)}>
          Gửi
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </li>
  )
}

export function ClarifySection() {
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
        Đội đang hỏi bạn <span className="badge">{questions.length}</span>
      </h3>
      <p className="muted">
        Nhân sự cần bạn làm rõ để tiếp tục việc — bấm một lựa chọn hoặc trả lời chi tiết.
        Câu trả lời được đưa vào bước tiếp theo của việc đó.
      </p>
      <ul className="clarify-list">
        {questions.map((q) => (
          <QuestionRow key={q.id} q={q} onDone={load} />
        ))}
      </ul>
    </section>
  )
}
