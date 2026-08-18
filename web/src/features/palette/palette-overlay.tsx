// The palette overlay: input, results, keyboard selection.
//
// Split from the chord listener so none of this — the results hook, the ops catalog
// types, the search client path — is in the entry bundle. It is only ever reachable
// after Cmd+K, which is a deliberate action with a natural moment to load.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useLanguage } from '../../i18n/language-context'
import { ASSISTANT_CONVERSATION_ID } from '../chat/conversation-list-state'
import type { PaletteItem } from './palette-items'
import { usePaletteResults } from './use-palette-results'

export function PaletteOverlay({ onClose }: { onClose: () => void }) {
  const { t } = useLanguage()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const { items, searching } = usePaletteResults(query)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // The list changes under the cursor as history arrives; clamping beats resetting,
  // which would yank the highlight back to the top mid-typing.
  useEffect(() => {
    setCursor((c) => Math.min(c, Math.max(0, items.length - 1)))
  }, [items.length])

  const pick = (item: PaletteItem) => {
    onClose()
    if (item.to) {
      navigate(item.to)
      return
    }
    // A command has no destination: it opens the assistant with the command in the
    // composer, ready to edit and send. The seed is the description, not the id — the
    // engine parses both (verified against the live engine: "get_status" and "Xem trạng
    // thái cả đội…" return the same fleet state), but only the description reads as a
    // sentence the CEO can extend, which is what most commands need ("tạo agent" → what
    // kind of agent).
    navigate(`/chat/${ASSISTANT_CONVERSATION_ID}?ask=${encodeURIComponent(item.label)}`)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor((c) => Math.min(c + 1, items.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (e.key === 'Enter' && items[cursor]) {
      e.preventDefault()
      pick(items[cursor])
    }
  }

  return (
    // Click-through on the backdrop closes: the palette is a transient overlay, and a
    // trapped one that only Escape dismisses is a worse accident than a stray close.
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label={t('palette.title')}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="palette-input"
          value={query}
          placeholder={t('palette.placeholder')}
          aria-label={t('palette.title')}
          onChange={(e) => {
            setQuery(e.target.value)
            setCursor(0)
          }}
          onKeyDown={onKeyDown}
        />
        <ul className="palette-results">
          {items.length === 0 ? (
            <li className="palette-empty">
              {searching ? t('palette.searching') : t('palette.empty')}
            </li>
          ) : (
            items.map((item, i) => (
              <li key={`${item.kind}:${item.id}`}>
                <button
                  type="button"
                  className={`palette-item is-${item.kind}${i === cursor ? ' is-cursor' : ''}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => pick(item)}
                >
                  <span className="palette-item-label">{item.label}</span>
                  {item.hint ? <span className="palette-item-hint">{item.hint}</span> : null}
                </button>
              </li>
            ))
          )}
          {searching && items.length > 0 ? (
            <li className="palette-empty">{t('palette.searching')}</li>
          ) : null}
        </ul>
      </div>
    </div>
  )
}
