// Modal focus trap (v56, first consumer: the artifact drawer). While mounted: initial
// focus moves to the container's first tabbable, Tab on the last tabbable wraps to the
// first (Shift+Tab reversed), and on unmount focus returns to whatever had it before
// the modal opened. Esc-to-close stays the caller's concern — this hook only owns WHERE
// focus can go, not when the modal closes.
import { useEffect, type RefObject } from 'react'

const TABBABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), ' +
  'select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function useFocusTrap(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const container = ref.current
    if (!container) return
    const restoreTo = document.activeElement as HTMLElement | null
    const tabbables = () => Array.from(container.querySelectorAll<HTMLElement>(TABBABLE))
    tabbables()[0]?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const els = tabbables()
      if (els.length === 0) return
      const first = els[0]
      const last = els[els.length - 1]
      const current = document.activeElement
      // Focus outside the trap (or on its edge) wraps back in — Tab can never escape.
      if (e.shiftKey && (current === first || !container.contains(current))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (current === last || !container.contains(current))) {
        e.preventDefault()
        first.focus()
      }
    }
    // Capture phase: wins over per-component keydown handlers regardless of tree order.
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      restoreTo?.focus?.()
    }
  }, [ref])
}
