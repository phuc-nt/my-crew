// The bell in the shell header: one place that answers "is anything waiting on me?"
// without visiting every hub. Rows deep-link to the surface that resolves them; a
// dismissed row stays hidden until its substance changes, a snoozed one until its
// clock runs out.
//
// Rendered outside `.app-header-actions` on purpose — that group collapses behind ⋯ on
// a phone, and the bell is the one control that must stay visible there.
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import { SNOOZE_DAY_MS, SNOOZE_HOUR_MS } from './snooze'
import { useAttentionItems } from './use-attention-items'

export function AttentionCenter() {
  const { t } = useLanguage()
  const { items, badge, hidden, snoozed, dismiss, dismissAll, snooze } = useAttentionItems()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Same close rules as the ⋯ menu: a pointer anywhere else, or Escape.
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

  const snoozeOptions = [
    { ms: SNOOZE_HOUR_MS, span: t('attention.snoozeHour') },
    { ms: SNOOZE_DAY_MS, span: t('attention.snoozeDay') },
  ]

  return (
    <div className="attention" ref={ref} data-walkthrough="bell">
      <button
        type="button"
        className="attention-bell"
        aria-label={t('attention.bellLabel', { n: badge })}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        🔔
        {badge > 0 && (
          <span className="attention-badge" data-testid="attention-badge">
            {badge}
          </span>
        )}
      </button>
      {open ? (
        <div
          className="attention-panel"
          role="dialog"
          aria-label={t('attention.title')}
          data-testid="attention-panel"
        >
          <div className="attention-head">
            <strong>{t('attention.title')}</strong>
            {items.length > 0 && (
              <Button variant="ghost" onClick={dismissAll}>
                {t('attention.markAll')}
              </Button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="attention-empty">{t('attention.empty')}</p>
          ) : (
            <ul className="attention-list">
              {items.map((item) => (
                <li
                  key={item.id}
                  className={`attention-item attention-${item.severity}`}
                  data-severity={item.severity}
                >
                  <Link to={item.to} onClick={() => setOpen(false)}>
                    <span className="attention-item-title">{item.title}</span>
                    {item.detail && <span className="attention-item-detail">{item.detail}</span>}
                  </Link>
                  <span className="attention-item-actions">
                    {snoozeOptions.map((opt) => (
                      <button
                        key={opt.ms}
                        type="button"
                        className="attention-snooze"
                        aria-label={t('attention.snoozeFor', { span: opt.span })}
                        title={t('attention.snoozeFor', { span: opt.span })}
                        onClick={() => snooze(item, opt.ms)}
                      >
                        {opt.span}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="attention-dismiss"
                      aria-label={t('attention.dismiss')}
                      onClick={() => dismiss(item)}
                    >
                      ✕
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {hidden > 0 && <p className="attention-hidden">{t('attention.hiddenN', { n: hidden })}</p>}
          {snoozed > 0 && (
            <p className="attention-hidden" data-testid="attention-snoozed">
              {t('attention.snoozedN', { n: snoozed })}
            </p>
          )}
        </div>
      ) : null}
    </div>
  )
}
