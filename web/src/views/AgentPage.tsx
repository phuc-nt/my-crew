// Unified agent page (v7 M18a): one place per agent — identity + status, activity (runs +
// cost), and a Telegram bind panel so a freshly-created agent can be made to chat WITHOUT
// touching .env. Composes existing read APIs (status/cost/runs); the only new write is the
// telegram bind. Reached from Team → click an agent, and from the create wizard on finish.
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError, api } from '../api/client'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { useLanguage } from '../i18n/language-context'
import { KIND_LABEL, RUN_STATUS_LABEL, formatCost, formatDateTime, labelFor } from '../labels'
import type { AgentStatus, CostPayload, RunsPayload } from '../types'
import { KnowledgeTab } from './AgentKnowledgeTab'

type Tab = 'activity' | 'telegram' | 'knowledge'

export function AgentPage() {
  const { t } = useLanguage()
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('activity')
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getAgentStatus(id)
      .then(setStatus)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('agentPage.loadError')))
  }, [id, t])

  if (error)
    return (
      <section>
        <p className="error">{t('agentPage.errorPrefix', { message: error })}</p>
        <p>
          {t('agentPage.orphanHint')}
          <Link to="/team">{t('agentPage.orphanHintLink')}</Link>
          {t('agentPage.orphanHintSuffix')}
        </p>
      </section>
    )
  if (!status) return <p>{t('agentPage.loading')}</p>

  return (
    <section className="agent-page">
      <header className="agent-page-head">
        <p className="agent-back">
          <Link to="/team">{t('agentPage.back')}</Link>
        </p>
        <h2>
          {status.name} <span className="muted">({id})</span>
        </h2>
        <Badge tone={status.enabled ? 'ok' : 'neutral'}>
          {status.enabled ? t('agentPage.enabled') : t('agentPage.disabled')}
        </Badge>
        {status.trust_mode && (
          <Badge
            tone={status.trust_mode === 'autonomous' ? 'accent' : 'warn'}
            title={
              status.trust_mode === 'autonomous'
                ? t('agentPage.trustAutonomousTitle')
                : t('agentPage.trustGuardedTitle')
            }
          >
            {status.trust_mode === 'autonomous' ? t('agentPage.trustAutonomous') : t('agentPage.trustGuarded')}
          </Badge>
        )}
        {status.pending_approvals > 0 && (
          <Link to="/work" className="agent-pending">
            {t('agentPage.pendingApprovals', { n: status.pending_approvals })}
          </Link>
        )}
      </header>

      <nav className="agent-tabs">
        <button
          type="button"
          className={tab === 'activity' ? 'tab-active' : undefined}
          onClick={() => setTab('activity')}
        >
          {t('agentPage.tabActivity')}
        </button>
        <button
          type="button"
          className={tab === 'telegram' ? 'tab-active' : undefined}
          onClick={() => setTab('telegram')}
        >
          {t('agentPage.tabTelegram')}
        </button>
        <button
          type="button"
          className={tab === 'knowledge' ? 'tab-active' : undefined}
          onClick={() => setTab('knowledge')}
        >
          {t('agentPage.tabKnowledge')}
        </button>
      </nav>

      {tab === 'activity' && <ActivityTab id={id} status={status} />}
      {tab === 'telegram' && <TelegramTab id={id} />}
      {tab === 'knowledge' && <KnowledgeTab id={id} />}
    </section>
  )
}

function ActivityTab({ id, status }: { id: string; status: AgentStatus }) {
  const { t } = useLanguage()
  const [cost, setCost] = useState<CostPayload | null>(null)
  const [runs, setRuns] = useState<RunsPayload | null>(null)
  useEffect(() => {
    api.getCost(id).then(setCost).catch(() => undefined)
    api.getRuns(id).then(setRuns).catch(() => undefined)
  }, [id])
  const ratio = cost && cost.cap > 0 ? cost.spent_this_month / cost.cap : 0
  return (
    <div>
      <p>
        {t('agentPage.costThisMonth')} <strong>{cost ? formatCost(cost.spent_this_month) : '…'}</strong>
        {cost && cost.cap > 0 && (
          <>
            {' '}/ {formatCost(cost.cap)} ({(ratio * 100).toFixed(0)}%
            {ratio >= (cost.warn_ratio ?? 0.8) ? ' ⚠️' : ''})
          </>
        )}
      </p>
      <p>
        {t('agentPage.lastRun')}{' '}
        {status.last_run ? `${status.last_run.kind} — ${status.last_run.status}` : t('agentPage.lastRunNone')}
      </p>
      <h4>{t('agentPage.runHistory')}</h4>
      {!runs || runs.runs.length === 0 ? (
        <EmptyState>{t('agentPage.noRuns')}</EmptyState>
      ) : (
        <ul className="agent-runs">
          {runs.runs.slice(0, 10).map((r, i) => (
            <li key={i}>
              {labelFor(KIND_LABEL, r.kind, t)} · {labelFor(RUN_STATUS_LABEL, r.status, t)} ·{' '}
              {formatDateTime(r.ts)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TelegramTab({ id }: { id: string }) {
  const { t } = useLanguage()
  const [token, setToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ bot_username?: string } | null>(null)
  const [chats, setChats] = useState<{ id: string; name: string }[] | null>(null)

  const bind = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.bindTelegram(id, token, chatId.trim() ? [chatId.trim()] : [])
      setResult({ bot_username: r.bot_username })
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('agentPage.telegramBindFailed'))
    } finally {
      setBusy(false)
    }
  }, [id, token, chatId, t])

  const loadChats = useCallback(async () => {
    setError(null)
    if (!token.trim()) {
      setError(t('agentPage.telegramNeedTokenFirst'))
      return
    }
    try {
      // uses the pasted token (not yet persisted) so you can pick a chat BEFORE binding
      const r = await api.telegramRecentChats(id, token)
      setChats(r.chats)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('agentPage.telegramChatsFailed'))
    }
  }, [id, token, t])

  return (
    <div className="telegram-tab">
      <p className="muted">
        {t('agentPage.telegramIntro')}
      </p>
      <label>
        {t('agentPage.telegramTokenLabel')}
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="123456:ABC-..."
        />
      </label>
      <label>
        {t('agentPage.telegramChatIdLabel')}
        <input value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder="5248565986" />
      </label>
      {chats && chats.length > 0 && (
        <ul className="telegram-chats">
          {chats.map((c) => (
            <li key={c.id}>
              <Button variant="chip" className="telegram-chip" onClick={() => setChatId(c.id)}>
                {c.id} {c.name && `(${c.name})`}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
      {result && (
        <p className="ok">{t('agentPage.telegramBoundNote', { username: result.bot_username ?? '' })}</p>
      )}
      <div className="agent-actions">
        <Button variant="ghost" onClick={() => void loadChats()}>
          {t('agentPage.telegramLoadChats')}
        </Button>
        <Button
          variant="primary"
          disabled={busy || !token.trim() || !chatId.trim()}
          onClick={() => void bind()}
          title={!chatId.trim() ? t('agentPage.telegramBindTitleHint') : undefined}
        >
          {busy ? t('agentPage.telegramBinding') : t('agentPage.telegramBind')}
        </Button>
      </div>
    </div>
  )
}
