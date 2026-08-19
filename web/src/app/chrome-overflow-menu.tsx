// Mobile-only overflow menu for the shell's chrome controls.
//
// On a phone the four controls (lens · language · theme · logout) each claimed their own
// wrapped row, pushing real content ~250px down the screen. They are all low-frequency —
// a CEO changes theme or language once, not once per task — so on mobile they collapse
// behind one button and the header stays a single row. Desktop renders them inline as
// before; this component is never mounted there.
import { useEffect, useRef, useState } from 'react'
import { ThemeToggle } from '../components/ThemeToggle'
import { Button } from '../components/ui/button'
import { useLanguage } from '../i18n/language-context'
import { useUiMode } from '../ui-mode-context'

export function ChromeOverflowMenu({ onLogout }: { onLogout: () => void }) {
  const { isHigh, setMode } = useUiMode()
  const { lang, setLang, t } = useLanguage()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Tapping anywhere else — or Escape — closes it. Without this the panel stays open
  // behind the next screen the CEO navigates to.
  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="chrome-overflow" ref={ref}>
      <button
        type="button"
        className="chrome-overflow-btn"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t('chrome.moreLabel')}
        onClick={() => setOpen((v) => !v)}
      >
        ⋯
      </button>
      {open ? (
        <div className="chrome-overflow-panel" role="menu">
          <Button
            variant="chip"
            className="mode-toggle"
            onClick={() => setMode(isHigh ? 'low' : 'high')}
            title={isHigh ? t('chrome.modeHighTitle') : t('chrome.modeLowTitle')}
          >
            {isHigh ? t('chrome.modeHigh') : t('chrome.modeLow')}
          </Button>
          <Button variant="chip" onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}>
            {lang === 'vi' ? 'VN' : 'EN'}
          </Button>
          <ThemeToggle />
          <button type="button" className="logout-btn" onClick={onLogout}>
            {t('chrome.logout')}
          </button>
        </div>
      ) : null}
    </div>
  )
}
