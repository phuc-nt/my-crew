// Đổi mật khẩu đăng nhập — trước đây chỉ đặt được một lần ở màn cài đặt ban đầu, sau đó
// muốn đổi phải sửa file .env bằng tay.
//
// Đổi xong là mọi phiên chết (backend xoay session secret) rồi dịch vụ tự khởi động lại,
// nên form không "lưu xong rồi thôi": nó dừng ở một màn nhắc đợi + đăng nhập lại. Đây là
// hành vi đúng, không phải lỗi — người ta đổi mật khẩu chính vì nghi có phiên lạ còn sống.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useLanguage } from '../../i18n/language-context'

const MIN_LEN = 6

export function ChangePasswordBox() {
  const { t } = useLanguage()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  // Máy dev chạy không đăng nhập thì không có mật khẩu nào để đổi — hỏi backend thay vì
  // đoán, rồi giấu hẳn ô này đi cho đỡ bày ra một nút chỉ để báo lỗi.
  const [authOn, setAuthOn] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    api
      .getMe()
      .then((m) => alive && setAuthOn(m.auth !== 'disabled'))
      .catch(() => alive && setAuthOn(false))
    return () => {
      alive = false
    }
  }, [])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    // Ô "nhập lại" chỉ sống ở FE — backend không cần biết, nhưng gõ nhầm mật khẩu mới rồi
    // bị đá ra ngoài thì không còn đường vào, nên chặn ngay tại đây.
    if (next !== confirm) {
      setError(t('password.mismatch'))
      return
    }
    if (next.length < MIN_LEN) {
      setError(t('password.tooShort', { min: String(MIN_LEN) }))
      return
    }
    setBusy(true)
    api
      .changePassword(current, next)
      .then((r) => {
        setDone(r.message)
        setCurrent('')
        setNext('')
        setConfirm('')
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : t('password.failed')),
      )
      .finally(() => setBusy(false))
  }

  if (authOn !== true) return null

  if (done) {
    return (
      <section className="mode-toggle-box">
        <h3>{t('password.title')}</h3>
        <p>{done}</p>
        <button type="button" onClick={() => window.location.reload()}>
          {t('password.backToLogin')}
        </button>
      </section>
    )
  }

  return (
    <section className="mode-toggle-box">
      <h3>{t('password.title')}</h3>
      <p className="muted">{t('password.hint')}</p>
      <form className="password-form" onSubmit={submit}>
        <label>
          {t('password.currentLabel')}
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </label>
        <label>
          {t('password.newLabel')}
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </label>
        <label>
          {t('password.confirmLabel')}
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </label>
        <button type="submit" disabled={busy || !current || !next}>
          {busy ? t('password.saving') : t('password.submit')}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  )
}
