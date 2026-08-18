// Cmd+K: one box over the whole app for "go somewhere", "ask the assistant something",
// "find something that happened".
//
// It owns no data of its own — navigation is the hub table, commands are the ops catalog,
// history is FTS5. What it adds is a single keyboard route to all three, so the CEO does
// not have to know which surface owns the answer before starting to type.
//
// This file is only the chord listener; everything the open palette needs is behind a
// lazy import, so a shortcut nobody presses costs the entry bundle nothing.
import { Suspense, lazy, useEffect, useState } from 'react'

const PaletteOverlay = lazy(() =>
  import('./palette-overlay').then((m) => ({ default: m.PaletteOverlay })),
)

/** True for the platform's palette chord: Cmd+K on macOS, Ctrl+K elsewhere. */
function isPaletteChord(e: KeyboardEvent): boolean {
  return (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'
}

export function CommandPalette() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isPaletteChord(e)) {
        e.preventDefault() // Chrome's own Cmd+K focuses the address bar.
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!open) return null

  // No fallback: the chunk is ~4 kB from the same origin, and a flashed spinner over the
  // whole app reads worse than the box appearing a frame later. Closing is always Escape.
  return (
    <Suspense fallback={null}>
      <PaletteOverlay onClose={() => setOpen(false)} />
    </Suspense>
  )
}
