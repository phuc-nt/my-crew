// Login screen (v6 M16): shown when the session is absent/expired. Posts credentials to
// /api/login; on success calls onLoggedIn so the app shell re-checks auth and renders the
// dashboard. Errors (wrong password 401, rate-limit 429) surface the backend's message.
import { useCallback, useState } from 'react'
import { ApiError, api } from '../api/client'

export function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (busy) return
      setBusy(true)
      setError(null)
      try {
        await api.login(username, password)
        onLoggedIn()
      } catch (err: unknown) {
        setError(err instanceof ApiError ? err.message : 'đăng nhập thất bại')
      } finally {
        setBusy(false)
      }
    },
    [username, password, busy, onLoggedIn],
  )

  return (
    <div className="login-screen">
      {/* v53: card padding/border/radius/shadow via .card (Card only renders a <div>;
          applied directly here to keep the <form> semantics). */}
      <form className="card login-box" onSubmit={submit}>
        <h1>Đăng nhập</h1>
        <label>
          Tên đăng nhập
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label>
          Mật khẩu
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="error">{error}</p>}
        {/* v53: styled by container element selector (.login-box button) — unify in a later pass */}
        <button type="submit" disabled={busy || !password}>
          {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </button>
      </form>
    </div>
  )
}
