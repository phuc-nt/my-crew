// Dual-lens P3 (high-mode only — Layout gates it): FTS5 history search in the header.
// Debounced fetch → dropdown; a hit navigates to where the thing lives: a `step` hit's
// ref is "<task_id>:<step_id>" → the office room for that task; an `audit` hit → the
// company-activity audit surface. Query escaping lives server-side in the index module.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api/client'
import type { HistorySearchHit } from '../types'

const DEBOUNCE_MS = 300

export function SearchBox() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<HistorySearchHit[]>([])
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    const query = q.trim()
    if (query.length < 2) {
      setHits([])
      setOpen(false)
      return
    }
    timer.current = setTimeout(() => {
      api.searchHistory(query).then((p) => {
        setHits(p.hits)
        setOpen(true)
      }).catch(() => undefined)
    }, DEBOUNCE_MS)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [q])

  const go = (hit: HistorySearchHit) => {
    setOpen(false)
    setQ('')
    if (hit.source === 'step') {
      const taskId = hit.ref.split(':')[0]
      navigate(`/office?room=${encodeURIComponent(taskId)}`)
    } else {
      navigate('/company-activity')
    }
  }

  return (
    <div className="header-search">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="tìm lịch sử…"
        aria-label="Tìm lịch sử làm việc"
      />
      {open && (
        <ul className="header-search-results">
          {/* v53: styled by container element selector (.header-search-results button) — unify in a later pass */}
          {hits.length === 0 && <li className="muted">Không có kết quả</li>}
          {hits.map((h, i) => (
            <li key={`${h.ref}-${i}`}>
              <button type="button" onMouseDown={() => go(h)}>
                <span className="muted">[{h.agent_id || h.source}]</span> {h.excerpt}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
