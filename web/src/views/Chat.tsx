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
import { useSharedPendingApprovals } from '../pending-approvals-context'

interface Turn {
  who: 'ceo' | 'agent'
  text: string
}

// v7 M20: fixed quick-action prompts on the assistant home so a CEO isn't staring at a blank
// box. Clicking one sends that message. A dynamic "duyệt" chip appears only when work waits.
const QUICK_CHIPS = ['Đội mình đang thế nào?', 'Tạo nhân sự ảo mới', 'Tổng chi phí tháng này?']

export function Chat() {
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
    searchParams.get('intent') === 'create-agent'
      ? 'Tạo nhân sự ảo mới. Hãy hỏi mình từng bước cần thiết.'
      : '',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const { count: pendingCount } = useSharedPendingApprovals()

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
        setUnavailableReason(e instanceof Error ? e.message : 'không kiểm tra được')
      })
  }, [])

  useEffect(() => {
    // guarded: jsdom (tests) has no scrollIntoView
    endRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [turns])

  const sendText = useCallback(
    async (message: string) => {
      if (!message.trim() || busy) return
      setTurns((t) => [...t, { who: 'ceo', text: message }])
      setDraft('')
      setBusy(true)
      setError(null)
      try {
        const res = await api.opsChat(message)
        setTurns((t) => [...t, { who: 'agent', text: res.reply }])
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'gửi thất bại')
      } finally {
        setBusy(false)
      }
    },
    [busy],
  )
  const send = useCallback(() => sendText(draft), [sendText, draft])

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  if (available === null) return <p>Đang kiểm tra…</p>
  if (available === false) {
    return (
      <section>
        <h2>Trợ lý điều hành</h2>
        <p className="error">Chưa dùng được: {unavailableReason}</p>
        {/* v9 P2: never a dead-end — the CEO can always create an agent via the wizard. */}
        <p>
          Bạn vẫn có thể <Link to="/create">tạo nhân sự ảo bằng biểu mẫu →</Link>
        </p>
      </section>
    )
  }

  return (
    <section className="ops-chat">
      <h2>Trợ lý điều hành</h2>
      <p className="ops-chat-hint">
        Nhắn tiếng Việt để quản lý đội: tạo agent, bật/tắt, xem trạng thái, xem chi phí. Mọi
        thay đổi đều được xem trước và cần bạn xác nhận.
      </p>
      {commands.length > 0 && (
        <details className="ops-chat-commands">
          <summary>Trợ lý làm được gì? ({commands.length} việc)</summary>
          <ul>
            {commands.map((c) => (
              <li key={c.id}>{c.description}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="ops-chat-log">
        {turns.length === 0 && (
          <EmptyState>
            Ví dụ: “đội mình đang có mấy agent, tốn bao nhiêu?” hoặc “tạo agent mã sales-pm,
            vai trò quản lý dự án”.
          </EmptyState>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`ops-chat-turn ops-chat-${t.who}`}>
            <span className="ops-chat-who">{t.who === 'ceo' ? 'Bạn' : 'Trợ lý'}</span>
            <pre className="ops-chat-text">{t.text}</pre>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {error && <p className="error">{error}</p>}
      <div className="quick-chips">
        {pendingCount > 0 && (
          <Link to="/work" className="chip chip-alert">
            ⚠️ {pendingCount} việc chờ duyệt
          </Link>
        )}
        {QUICK_CHIPS.map((c) => (
          <Button key={c} variant="chip" disabled={busy} onClick={() => void sendText(c)}>
            {c}
          </Button>
        ))}
      </div>
      <div className="ops-chat-input">
        <input
          type="text"
          value={draft}
          placeholder="Nhắn cho trợ lý…"
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <Button variant="primary" onClick={() => void send()} disabled={busy || !draft.trim()}>
          {busy ? 'Đang gửi…' : 'Gửi'}
        </Button>
      </div>
    </section>
  )
}
