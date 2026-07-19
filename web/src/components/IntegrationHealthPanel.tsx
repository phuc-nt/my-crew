// Integration health panel (Team view + Settings): green/red dot + label per check from
// GET /api/health/integrations. A failing check shows detail + a fix hint so whoever does the
// technical setup sees what's broken and how to fix it. v10 M26: any shell command inside the
// hint (wrapped in `backticks`) renders as a copy-paste <code> block. Manual refresh button —
// the backend caches for 30s so polling is not needed.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Button } from './ui/button'
import type { IntegrationCheck } from '../types'

// Split a hint into text + inline-code spans on `backtick` boundaries so the shell commands in a
// remediation hint are visually distinct and easy to copy. Returns React nodes. Text children are
// auto-escaped by React (no XSS). An UNBALANCED (odd) backtick count means the last segment has no
// closing backtick, so it's treated as plain text, not a runaway <code>.
function renderHint(hint: string) {
  const parts = hint.split('`')
  const codeUntil = parts.length % 2 === 0 ? parts.length : parts.length - 1
  return parts.map((part, i) =>
    i % 2 === 1 && i < codeUntil ? (
      <code key={i} className="health-fix-cmd">
        {part}
      </code>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}

export function IntegrationHealthPanel() {
  const [checks, setChecks] = useState<IntegrationCheck[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getIntegrationHealth()
      .then((res) => setChecks(res.checks))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'không kiểm tra được kết nối'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failing = checks.filter((c) => !c.ok).length

  return (
    <section className="health-panel">
      <h3>
        Sức khỏe hệ thống{' '}
        <Button variant="ghost" disabled={loading} onClick={load}>
          {loading ? 'Đang kiểm tra…' : 'Làm mới'}
        </Button>
      </h3>
      {error && <p className="error">Lỗi: {error}</p>}
      {!error && !loading && (
        <p className="muted">
          {failing === 0
            ? '✓ Tất cả kết nối đều sẵn sàng.'
            : `${failing} mục cần khắc phục — làm theo gợi ý bên dưới.`}
        </p>
      )}
      <ul className="health-checks">
        {checks.map((c) => (
          <li key={c.id} className={c.ok ? 'health-ok' : 'health-fail'}>
            <span className={c.ok ? 'health-dot health-dot-ok' : 'health-dot health-dot-fail'} />{' '}
            {c.label}
            {!c.ok && (
              <div className="muted health-detail">
                {c.detail} — {renderHint(c.hint)}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
