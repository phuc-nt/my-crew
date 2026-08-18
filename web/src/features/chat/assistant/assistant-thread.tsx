// The assistant conversation: ops commands answered by the admin agent.
//
// Shaped like every other thread in the hub (log above, composer below) so switching
// between a workroom and the assistant does not change how the pane behaves.
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useLanguage } from '../../../i18n/language-context'
import { useOpsChat } from './use-ops-chat'

export function AssistantThread({ title }: { title: string }) {
  const { t } = useLanguage()
  const { available, unavailableReason, commands, turns, busy, error, send } = useOpsChat()
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Guarded: jsdom has no scrollIntoView.
    endRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [turns])

  const submit = (message: string) => {
    setDraft('')
    void send(message)
  }

  if (available === null) {
    return (
      <section className="chat-thread" aria-label={title}>
        <p className="chat-thread-empty">{t('chat.checking')}</p>
      </section>
    )
  }

  if (available === false) {
    return (
      <section className="chat-thread" aria-label={title}>
        <p className="error">{t('chat.unavailablePrefix', { reason: unavailableReason })}</p>
        {/* Never a dead end: the wizard can always create an agent without the ops engine.
            Still /create — the team hub takes that route over in a later phase. */}
        <p>
          {t('chat.createViaWizardPrefix')}
          <Link to="/create">{t('chat.createViaWizardLink')}</Link>
        </p>
      </section>
    )
  }

  const quickChips = [
    t('chat.quickChipStatus'),
    t('chat.quickChipCreateAgent'),
    t('chat.quickChipCost'),
  ]

  return (
    <section className="chat-thread" aria-label={title}>
      <header className="chat-thread-head">
        <h2 className="chat-thread-title" title={title}>{title}</h2>
      </header>

      <div className="chat-thread-log ops-thread-log">
        {turns.length === 0 ? (
          <p className="chat-thread-empty">{t('chat.emptyExample')}</p>
        ) : null}
        {turns.map((turn, i) => (
          <div key={i} className={`ops-turn is-${turn.who}`}>
            <span className="ops-turn-who">
              {turn.who === 'ceo' ? t('chat.who.ceo') : t('chat.who.agent')}
            </span>
            <pre className="ops-turn-text">{turn.text}</pre>
          </div>
        ))}
        {/* A real ops turn takes seconds (measured: 5.6s for the cost query against the
            live engine). Without this the CEO sees their own message and nothing else,
            which reads as a dropped send. */}
        {busy ? <p className="ops-thinking">{t('chat.thinking')}</p> : null}
        <div ref={endRef} />
      </div>

      {error ? <p className="error">{error}</p> : null}

      <div className="ops-composer">
        <div className="ops-chips">
          {quickChips.map((c) => (
            <button
              key={c}
              type="button"
              className="ops-chip"
              disabled={busy}
              onClick={() => submit(c)}
            >
              {c}
            </button>
          ))}
          {commands.length > 0 ? (
            <details className="ops-commands">
              <summary>{t('chat.commandsSummary', { n: commands.length })}</summary>
              <ul>
                {commands.map((c) => (
                  <li key={c.id}>{c.description}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
        <form
          className="ops-input-row"
          onSubmit={(e) => {
            e.preventDefault()
            if (draft.trim()) submit(draft)
          }}
        >
          <input
            type="text"
            value={draft}
            placeholder={t('chat.inputPlaceholder')}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className="ops-send" disabled={busy || !draft.trim()}>
            {busy ? t('chat.sending') : t('chat.send')}
          </button>
        </form>
      </div>
    </section>
  )
}
