// Wizard Step 5: JSON-ish summary of the spec that will be POSTed, a copy-to-clipboard
// .env template (NAMES only — secrets are never entered here, see env-template.ts), and
// the Create button. 400/409 surface the backend's exact `detail` string inline.
import { useState } from 'react'
import { Link } from 'react-router'
import { api, ApiError } from '../api/client'
import { Button } from '../components/ui/button'
import type { CreateAgentResult, CreateAgentSpec } from '../types'
import { buildEnvTemplate } from './env-template'

export function ReviewStep({ spec, pack }: { spec: CreateAgentSpec; pack: { servers: string[] } | null }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CreateAgentResult | null>(null)
  const [copied, setCopied] = useState(false)

  const envTemplate = buildEnvTemplate(pack?.servers ?? [])

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const res = await api.createAgent(spec)
      setResult(res)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'tạo thất bại')
    } finally {
      setBusy(false)
    }
  }

  async function copyEnv() {
    try {
      await navigator.clipboard.writeText(envTemplate)
      setCopied(true)
    } catch {
      /* clipboard unavailable — the text is still selectable below */
    }
  }

  return (
    <section>
      <h3>Bước 5: Xem lại + tạo</h3>
      <pre className="review-spec">{JSON.stringify(spec, null, 2)}</pre>

      <div className="token-setup-box">
        <h4>Cài đặt token</h4>
        <p className="muted">
          Đây chỉ là TÊN biến môi trường — đừng nhập giá trị bí mật ở đây. Người phụ trách kỹ
          thuật sẽ điền giá trị thật vào file .env trên máy chủ.
        </p>
        <pre className="env-template">{envTemplate}</pre>
        <Button variant="ghost" onClick={copyEnv}>
          {copied ? 'Đã chép!' : 'Chép mẫu .env'}
        </Button>
      </div>

      {error && <p className="error">Lỗi: {error}</p>}
      {!result && (
        <Button variant="ghost" disabled={busy} onClick={create}>
          {busy ? 'Đang tạo…' : 'Tạo agent'}
        </Button>
      )}
      {result && (
        <p className="ok">
          Đã tạo agent <strong>{result.created.id}</strong>.{' '}
          <Link to={`/agents/${result.created.id}`}>Mở trang agent</Link> để gắn bot Telegram
          (nhắn được ngay) và quản lý.
        </p>
      )}
    </section>
  )
}
