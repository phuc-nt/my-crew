// `?` opens a card listing every global chord; `g` + a letter jumps between hubs.
//
// Both listeners ignore keystrokes typed into an input, textarea, or contenteditable —
// a `?` in a chat message must stay a `?`. The card can also be opened by dispatching
// SHORTCUTS_OPEN_EVENT on window, which is how the header's ⌨ button reaches it without
// the two sharing state.
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useLanguage } from '../../i18n/language-context'
import type { UiKey } from '../../i18n/dictionary'
import { WALKTHROUGH_OPEN_EVENT } from '../onboarding/walkthrough-state'

export const SHORTCUTS_OPEN_EVENT = 'my-crew:shortcuts-help'

/** After a bare `g`, the hub letter must follow within this window. */
const CHORD_WINDOW_MS = 1000

const HUB_JUMPS: { key: string; to: string; labelKey: UiKey }[] = [
  { key: 'c', to: '/chat', labelKey: 'hub.chat' },
  { key: 'o', to: '/office', labelKey: 'hub.office' },
  { key: 'w', to: '/work', labelKey: 'hub.work' },
  { key: 't', to: '/team', labelKey: 'hub.team' },
  { key: 's', to: '/system', labelKey: 'hub.system' },
]

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

export function ShortcutsHelp() {
  const { t } = useLanguage()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const pendingG = useRef<number | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'Escape') {
        setOpen(false)
        return
      }
      if (isEditable(e.target)) return
      if (e.key === '?') {
        e.preventDefault()
        setOpen((v) => !v)
        return
      }
      const now = Date.now()
      if (e.key === 'g') {
        pendingG.current = now
        return
      }
      const armed = pendingG.current !== null && now - pendingG.current < CHORD_WINDOW_MS
      pendingG.current = null
      if (!armed) return
      const jump = HUB_JUMPS.find((h) => h.key === e.key.toLowerCase())
      if (jump) {
        e.preventDefault()
        setOpen(false)
        void navigate(jump.to)
      }
    }
    const onOpen = () => setOpen(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener(SHORTCUTS_OPEN_EVENT, onOpen)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(SHORTCUTS_OPEN_EVENT, onOpen)
    }
  }, [navigate])

  if (!open) return null

  const rows: { keys: string[]; label: string }[] = [
    { keys: [IS_MAC ? '⌘' : 'Ctrl', 'K'], label: t('shortcuts.palette') },
    { keys: ['?'], label: t('shortcuts.help') },
    { keys: ['Esc'], label: t('shortcuts.close') },
    ...HUB_JUMPS.map((h) => ({ keys: ['g', h.key], label: t('shortcuts.goTo', { hub: t(h.labelKey) }) })),
  ]

  return (
    <div className="shortcuts-backdrop" onClick={() => setOpen(false)}>
      <div
        className="shortcuts-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t('shortcuts.title')}
        data-testid="shortcuts-help"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>{t('shortcuts.title')}</h3>
        <table className="shortcuts-table">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td>
                  {row.keys.map((k, i) => (
                    <span key={k}>
                      {i > 0 && ' '}
                      <kbd>{k}</kbd>
                    </span>
                  ))}
                </td>
                <td>{row.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">{t('shortcuts.hint')}</p>
        <button
          type="button"
          className="shortcuts-walkthrough"
          onClick={() => {
            setOpen(false)
            window.dispatchEvent(new Event(WALKTHROUGH_OPEN_EVENT))
          }}
        >
          {t('walkthrough.reopen')}
        </button>
      </div>
    </div>
  )
}
