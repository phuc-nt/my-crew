// Kênh — bind a Telegram bot to this agent without touching .env. Ported from the old
// agent page's telegram tab.
import { useCallback, useState } from 'react'
import { ApiError, api } from '../../../api/client'
import { Button } from '../../../components/ui/button'
import { useLanguage } from '../../../i18n/language-context'

export function ChannelsTab({ id }: { id: string }) {
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
      // Uses the pasted, not-yet-persisted token so a chat can be picked BEFORE binding.
      const r = await api.telegramRecentChats(id, token)
      setChats(r.chats)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('agentPage.telegramChatsFailed'))
    }
  }, [id, token, t])

  return (
    <div className="telegram-tab">
      <p className="muted">{t('agentPage.telegramIntro')}</p>
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
        <p className="ok">
          {t('agentPage.telegramBoundNote', { username: result.bot_username ?? '' })}
        </p>
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
