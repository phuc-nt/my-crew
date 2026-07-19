// CEO chat-ops view (v6 M14b): a chat box that talks to the admin agent's ops engine in
// Vietnamese — create agents, enable/disable, ask status/cost. It POSTs each message to
// /api/ops/chat, which drives the SAME engine + SAME per-operator conversation store as the
// Telegram DM path, so a dialogue can span both surfaces. No SSE: an ops reply is one short
// turn (request/response), not a streamed run.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { useSharedPendingApprovals } from '../pending-approvals-context'

interface Turn {
  who: 'ceo' | 'agent'
  text: string
}

export function Chat() {
  const { t } = useLanguage()
  const [available, setAvailable] = useState<boolean | null>(null)
  // v32 discoverability: the real ops catalog, shown up front instead of only after a miss.
  const [commands, setCommands] = useState<{ id: string; description: string }[]>([])
  const [unavailableReason, setUnavailableReason] = useState<string>('')
  const [turns, setTurns] = useState<Turn[]>([])
  // v9 P2: prefill a create-agent starter prompt when arriving from Team's "+ Tạo nhân sự ảo"
  // (?intent=create-agent). A lazy initializer reads the param ONCE at mount, so it can't
  // clobber the CEO's later typing if searchParams changes reference.
  const [searchParams] = useSearchParams()
  const [draft, setDraft] = useState(() =>
    searchParams.get('intent') === 'create-agent' ? t('chat.createAgentPrefill') : '',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const { count: pendingCount } = useSharedPendingApprovals()

  // v7 M20: fixed quick-action prompts on the assistant home so a CEO isn't staring at a
  // blank box. Clicking one sends that message. A dynamic "duyệt" chip appears only when
  // work waits.
  const quickChips = [t('chat.quickChipStatus'), t('chat.quickChipCreateAgent'), t('chat.quickChipCost')]

  useEffect(() => {
    api.getOpsChatCommands().then((r) => setCommands(r.commands)).catch(() => setCommands([]))
    api
      .opsChatAvailable()
      .then((r) => {
        setAvailable(r.available)
        if (!r.available) setUnavailableReason(r.reason ?? '')
      })
      .catch((e: unknown) => {
        setAvailable(false)
        setUnavailableReason(e instanceof Error ? e.message : t('chat.checkFailed'))
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // guarded: jsdom (tests) has no scrollIntoView
    endRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [turns])

  const sendText = useCallback(
    async (message: string) => {
      if (!message.trim() || busy) return
      setTurns((prev) => [...prev, { who: 'ceo', text: message }])
      setDraft('')
      setBusy(true)
      setError(null)
      try {
        const res = await api.opsChat(message)
        setTurns((prev) => [...prev, { who: 'agent', text: res.reply }])
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : t('chat.sendFailed'))
      } finally {
        setBusy(false)
      }
    },
    [busy, t],
  )
  const send = useCallback(() => sendText(draft), [sendText, draft])

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  if (available === null) return <p>{t('chat.checking')}</p>
  if (available === false) {
    return (
      <section>
        <PageHeader title={t('chat.title')} />
        <p className="error">{t('chat.unavailablePrefix', { reason: unavailableReason })}</p>
        {/* v9 P2: never a dead-end — the CEO can always create an agent via the wizard. */}
        <p>
          {t('chat.createViaWizardPrefix')}
          <Link to="/create">{t('chat.createViaWizardLink')}</Link>
        </p>
      </section>
    )
  }

  return (
    <section className="ops-chat">
      <PageHeader title={t('chat.title')} />
      <p className="ops-chat-hint">{t('chat.hint')}</p>
      {commands.length > 0 && (
        <details className="ops-chat-commands">
          <summary>{t('chat.commandsSummary', { n: commands.length })}</summary>
          <ul>
            {commands.map((c) => (
              <li key={c.id}>{c.description}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="ops-chat-log">
        {turns.length === 0 && <EmptyState>{t('chat.emptyExample')}</EmptyState>}
        {turns.map((turn, i) => (
          <div key={i} className={`ops-chat-turn ops-chat-${turn.who}`}>
            <span className="ops-chat-who">
              {turn.who === 'ceo' ? t('chat.who.ceo') : t('chat.who.agent')}
            </span>
            <pre className="ops-chat-text">{turn.text}</pre>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {error && <p className="error">{error}</p>}
      <div className="quick-chips">
        {pendingCount > 0 && (
          <Link to="/work" className="chip chip-alert">
            {t('chat.pendingChip', { n: pendingCount })}
          </Link>
        )}
        {quickChips.map((c) => (
          <Button key={c} variant="chip" disabled={busy} onClick={() => void sendText(c)}>
            {c}
          </Button>
        ))}
      </div>
      <div className="ops-chat-input">
        <input
          type="text"
          value={draft}
          placeholder={t('chat.inputPlaceholder')}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <Button variant="primary" onClick={() => void send()} disabled={busy || !draft.trim()}>
          {busy ? t('chat.sending') : t('chat.send')}
        </Button>
      </div>
    </section>
  )
}
