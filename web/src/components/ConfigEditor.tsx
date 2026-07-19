// Editor for one profile file. MEMORY.md is rendered read-only (the agent self-writes it;
// no save route exists). Save surfaces the backend's EXACT validation message on a 400.
import { useState } from 'react'
import { Button } from './ui/button'

export function ConfigEditor({
  label,
  initial,
  readOnly,
  onSave,
}: {
  label: string
  initial: string
  readOnly?: boolean
  onSave?: (text: string) => Promise<void>
}) {
  const [text, setText] = useState(initial)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    if (!onSave) return
    setBusy(true)
    setStatus(null)
    setError(null)
    try {
      await onSave(text)
      setStatus('Đã lưu.')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'lưu thất bại')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="config-editor">
      <h3>
        {label}
        {readOnly ? ' (chỉ đọc)' : ''}
      </h3>
      <textarea
        value={text}
        readOnly={readOnly}
        rows={12}
        onChange={(e) => setText(e.target.value)}
      />
      {!readOnly && (
        <div>
          <Button variant="ghost" disabled={busy} onClick={save}>
            {busy ? 'Đang lưu…' : 'Lưu'}
          </Button>
          {status && <span className="ok"> {status}</span>}
          {error && <span className="error"> {error}</span>}
        </div>
      )}
    </div>
  )
}
