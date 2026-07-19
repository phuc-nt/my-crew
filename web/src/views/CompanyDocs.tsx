// v7 M19: the Company Docs library — the CEO's shared document store. Paste a document
// (leave policy, directory, conventions…), and tick it onto agents from their agent page.
// A plain textarea editor (no rich text — YAGNI); the body injects into agents' INTERNAL
// prompt only (external reports never see it, enforced server-side).
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import { Button } from '../components/ui/button'
import { PageHeader } from '../components/ui/page-header'
import type { CompanyDoc } from '../types'

export function CompanyDocs() {
  const [docs, setDocs] = useState<CompanyDoc[] | null>(null)
  const [selected, setSelected] = useState<CompanyDoc | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .listCompanyDocs()
      .then((r) => setDocs(r.docs))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'lỗi'))
  }, [])
  useEffect(load, [load])

  if (error) return <p className="error">Lỗi: {error}</p>
  if (!docs) return <p>Đang tải…</p>

  return (
    <section className="company-docs">
      <PageHeader
        title="Tài liệu công ty"
        actions={
          <Button variant="ghost" onClick={() => setSelected('new')}>
            + Tài liệu mới
          </Button>
        }
      />
      <p className="muted">
        Tài liệu ở đây được tick cho từng agent (trong trang agent → tab Kiến thức) và chỉ
        đưa vào ngữ cảnh nội bộ — báo cáo gửi ra ngoài không bao giờ chứa nội dung này.
      </p>
      <div className="company-docs-body">
        <ul className="company-docs-list">
          {/* v53: styled by container element selector (.company-docs-list button) — unify in a later pass */}
          {docs.length === 0 && <li className="muted">Chưa có tài liệu nào.</li>}
          {docs.map((d) => (
            <li key={d.slug}>
              <button
                type="button"
                className={selected !== 'new' && selected?.slug === d.slug ? 'active' : undefined}
                onClick={() => setSelected(d)}
              >
                <strong>{d.title}</strong>
                {d.updated && <span className="muted"> · {d.updated}</span>}
              </button>
            </li>
          ))}
        </ul>
        {selected && (
          <DocEditor
            doc={selected === 'new' ? null : selected}
            onSaved={() => {
              setSelected(null)
              load()
            }}
            onDeleted={() => {
              setSelected(null)
              load()
            }}
            onCancel={() => setSelected(null)}
          />
        )}
      </div>
    </section>
  )
}

function DocEditor({
  doc,
  onSaved,
  onDeleted,
  onCancel,
}: {
  doc: CompanyDoc | null
  onSaved: () => void
  onDeleted: () => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(doc?.title ?? '')
  const [body, setBody] = useState(doc?.body ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = useCallback(async () => {
    setBusy(true)
    setError(null)
    const today = new Date().toISOString().slice(0, 10)
    try {
      if (doc) await api.updateCompanyDoc(doc.slug, title, body, today)
      else await api.createCompanyDoc(title, body, today)
      onSaved()
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : 'lưu thất bại')
    } finally {
      setBusy(false)
    }
  }, [doc, title, body, onSaved])

  const remove = useCallback(async () => {
    if (!doc) return
    if (!window.confirm(`Xóa tài liệu "${doc.title}"?`)) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteCompanyDoc(doc.slug)
      onDeleted()
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : 'xóa thất bại')
    } finally {
      setBusy(false)
    }
  }, [doc, onDeleted])

  return (
    <div className="company-doc-editor">
      <label>
        Tiêu đề
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Quy trình nghỉ phép" />
      </label>
      <label>
        Nội dung
        <textarea rows={16} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="agent-actions">
        {/* v53: styled by container element selector (.agent-actions button) — unify in a later pass */}
        <button type="button" disabled={busy || !title.trim()} onClick={() => void save()}>
          {busy ? 'Đang lưu…' : 'Lưu'}
        </button>
        <button type="button" onClick={onCancel}>
          Hủy
        </button>
        {doc && (
          <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>
            Xóa
          </button>
        )}
      </div>
    </div>
  )
}
