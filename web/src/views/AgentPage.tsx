// Unified agent page (v7 M18a): one place per agent — identity + status, activity (runs +
// cost), and a Telegram bind panel so a freshly-created agent can be made to chat WITHOUT
// touching .env. Composes existing read APIs (status/cost/runs); the only new write is the
// telegram bind. Reached from Team → click an agent, and from the create wizard on finish.
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError, api } from '../api/client'
import type { AgentStatus, CostPayload, RunsPayload } from '../types'
import { KnowledgeTab } from './AgentKnowledgeTab'

type Tab = 'activity' | 'telegram' | 'knowledge'

export function AgentPage() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('activity')
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getAgentStatus(id)
      .then(setStatus)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'lỗi'))
  }, [id])

  if (error) return <p className="error">Lỗi: {error}</p>
  if (!status) return <p>Đang tải…</p>

  return (
    <section className="agent-page">
      <header className="agent-page-head">
        <h2>
          {status.name} <span className="muted">({id})</span>
        </h2>
        <span className={status.enabled ? 'badge-on' : 'badge-off'}>
          {status.enabled ? 'đang bật' : 'đang tắt'}
        </span>
        {status.pending_approvals > 0 && (
          <Link to="/work" className="agent-pending">
            {status.pending_approvals} việc chờ duyệt
          </Link>
        )}
      </header>

      <nav className="agent-tabs">
        <button
          type="button"
          className={tab === 'activity' ? 'tab-active' : undefined}
          onClick={() => setTab('activity')}
        >
          Hoạt động
        </button>
        <button
          type="button"
          className={tab === 'telegram' ? 'tab-active' : undefined}
          onClick={() => setTab('telegram')}
        >
          Kênh Telegram
        </button>
        <button
          type="button"
          className={tab === 'knowledge' ? 'tab-active' : undefined}
          onClick={() => setTab('knowledge')}
        >
          Kiến thức
        </button>
      </nav>

      {tab === 'activity' && <ActivityTab id={id} status={status} />}
      {tab === 'telegram' && <TelegramTab id={id} />}
      {tab === 'knowledge' && <KnowledgeTab id={id} />}
    </section>
  )
}

function ActivityTab({ id, status }: { id: string; status: AgentStatus }) {
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
        Chi phí tháng này:{' '}
        <strong>${cost ? cost.spent_this_month.toFixed(4) : '…'}</strong>
        {cost && cost.cap > 0 && (
          <>
            {' '}/ ${cost.cap.toFixed(2)} ({(ratio * 100).toFixed(0)}%
            {ratio >= (cost.warn_ratio ?? 0.8) ? ' ⚠️' : ''})
          </>
        )}
      </p>
      <p>
        Lần chạy gần nhất:{' '}
        {status.last_run
          ? `${status.last_run.kind} — ${status.last_run.status}`
          : 'chưa có'}
      </p>
      <h4>Lịch sử chạy</h4>
      {!runs || runs.runs.length === 0 ? (
        <p className="muted">Chưa có lần chạy nào.</p>
      ) : (
        <ul className="agent-runs">
          {runs.runs.slice(0, 10).map((r, i) => (
            <li key={i}>
              {r.kind} · {r.status} · {r.ts}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TelegramTab({ id }: { id: string }) {
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
      setError(e instanceof ApiError ? e.message : 'gắn bot thất bại')
    } finally {
      setBusy(false)
    }
  }, [id, token, chatId])

  const loadChats = useCallback(async () => {
    setError(null)
    if (!token.trim()) {
      setError('Nhập token bot trước, rồi bấm "Lấy chat gần đây".')
      return
    }
    try {
      // uses the pasted token (not yet persisted) so you can pick a chat BEFORE binding
      const r = await api.telegramRecentChats(id, token)
      setChats(r.chats)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : 'không lấy được chat')
    }
  }, [id, token])

  return (
    <div className="telegram-tab">
      <p className="muted">
        Tạo bot qua @BotFather (gửi <code>/newbot</code>, đặt tên + ảnh), copy token rồi dán
        vào đây. Agent sẽ có danh tính Telegram riêng — nhận câu hỏi + lệnh + báo cáo.
      </p>
      <label>
        Bot token (từ BotFather)
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="123456:ABC-..."
        />
      </label>
      <label>
        Chat id (DM của bạn — bấm "Lấy chat" sau khi nhắn bot 1 câu)
        <input value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder="5248565986" />
      </label>
      {chats && chats.length > 0 && (
        <ul className="telegram-chats">
          {chats.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => setChatId(c.id)}>
                {c.id} {c.name && `(${c.name})`}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
      {result && (
        <p className="ok">
          ✓ Đã gắn bot <strong>@{result.bot_username}</strong>. Nhắn thử cho bot — agent sẽ trả
          lời trong ~1 phút (dịch vụ poll theo nhịp).
        </p>
      )}
      <div className="agent-actions">
        <button type="button" onClick={() => void loadChats()}>
          Lấy chat gần đây
        </button>
        <button
          type="button"
          disabled={busy || !token.trim() || !chatId.trim()}
          onClick={() => void bind()}
          title={!chatId.trim() ? 'Cần chat id — nhắn bot rồi bấm "Lấy chat gần đây"' : undefined}
        >
          {busy ? 'Đang gắn…' : 'Gắn bot'}
        </button>
      </div>
    </div>
  )
}

