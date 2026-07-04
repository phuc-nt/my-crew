// v7 M20: "Cài đặt" — integration health at a glance + a "Nâng cao" section linking the
// technical views the CEO rarely needs (they keep their original components, just moved out
// of the top nav so the daily surface stays 4 items). No backend change.
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import type { IntegrationHealthPayload } from '../types'

// Technical / power-user views — moved here from the flat nav. Nothing is removed; each
// route still renders its existing component.
const ADVANCED = [
  { to: '/overview', label: 'Tổng quan (biểu đồ)' },
  { to: '/company-docs', label: 'Tài liệu công ty' },
  { to: '/create', label: 'Tạo nhân sự ảo' },
  { to: '/timeline', label: 'Timeline hoạt động' },
  { to: '/cost', label: 'Chi phí' },
  { to: '/memory', label: 'Bộ nhớ & Tự động hoá' },
  { to: '/guardrail', label: 'Guardrail (rào chắn)' },
  { to: '/config', label: 'Cấu hình agent' },
  { to: '/trigger', label: 'Chạy báo cáo thủ công' },
]

export function Settings() {
  const [health, setHealth] = useState<IntegrationHealthPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getIntegrationHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'lỗi'))
  }, [])

  return (
    <section className="settings-page">
      <h2>Cài đặt</h2>

      <section>
        <h3>Kết nối</h3>
        {error && <p className="error">Lỗi: {error}</p>}
        {!health ? (
          <p>Đang kiểm tra…</p>
        ) : (
          <ul className="integration-health">
            {health.checks.map((c) => (
              <li key={c.id} className={c.ok ? 'ok' : 'error'}>
                <strong>{c.ok ? '✓' : '✕'} {c.label}</strong>
                <span className="muted"> — {c.detail}</span>
                {!c.ok && c.hint && <div className="muted">{c.hint}</div>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3>Nâng cao</h3>
        <p className="muted">
          Các trang kỹ thuật — bình thường không cần, nhưng vẫn đầy đủ khi bạn muốn xem sâu.
        </p>
        <ul className="advanced-links">
          {ADVANCED.map((a) => (
            <li key={a.to}>
              <Link to={a.to}>{a.label}</Link>
            </li>
          ))}
        </ul>
      </section>
    </section>
  )
}
