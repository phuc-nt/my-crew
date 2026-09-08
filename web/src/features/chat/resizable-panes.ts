// v96: the chat hub's two side columns are draggable. Pure part: the limits, the
// persisted shape, and the arithmetic of a drag — so the component only wires pointer
// events to these and the unit test needs no layout engine.

export const PANE_WIDTHS_STORAGE_KEY = 'my-crew.chat.paneWidths'

export type ResizablePane = 'list' | 'pending'

export interface PaneWidths {
  list: number
  pending: number
}

export const DEFAULT_PANE_WIDTHS: PaneWidths = { list: 280, pending: 300 }

/** Narrower than the min and the column stops being useful; wider than the max and
 *  the thread — the reason the hub exists — is what gives. */
export const PANE_LIMITS: Record<ResizablePane, { min: number; max: number }> = {
  list: { min: 200, max: 480 },
  pending: { min: 220, max: 520 },
}

/** Keyboard nudge on the separator, in px per arrow press. */
export const KEYBOARD_STEP_PX = 16

export function clampPaneWidth(pane: ResizablePane, px: number): number {
  const { min, max } = PANE_LIMITS[pane]
  if (!Number.isFinite(px)) return DEFAULT_PANE_WIDTHS[pane]
  return Math.round(Math.min(max, Math.max(min, px)))
}

/** The list sits left of its handle (grows with +dx); the pending pane sits right of
 *  its handle (grows with -dx). */
export function draggedWidth(
  pane: ResizablePane,
  startWidth: number,
  startX: number,
  currentX: number,
): number {
  const dx = currentX - startX
  return clampPaneWidth(pane, pane === 'list' ? startWidth + dx : startWidth - dx)
}

export function readPaneWidths(): PaneWidths {
  try {
    const raw = localStorage.getItem(PANE_WIDTHS_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PANE_WIDTHS }
    const parsed = JSON.parse(raw) as Partial<Record<ResizablePane, unknown>>
    return {
      list: clampPaneWidth('list', Number(parsed.list ?? DEFAULT_PANE_WIDTHS.list)),
      pending: clampPaneWidth('pending', Number(parsed.pending ?? DEFAULT_PANE_WIDTHS.pending)),
    }
  } catch {
    return { ...DEFAULT_PANE_WIDTHS }
  }
}

export function writePaneWidths(widths: PaneWidths): void {
  try {
    localStorage.setItem(PANE_WIDTHS_STORAGE_KEY, JSON.stringify(widths))
  } catch {
    // Private mode / quota: the width holds for this page load.
  }
}

/** The CSS custom properties the grid reads. Kept as a function so the page sets both
 *  in one style object and the stylesheet stays the single owner of the fallbacks. */
export function paneWidthVars(widths: PaneWidths): Record<string, string> {
  return {
    '--chat-list-w': `${widths.list}px`,
    '--chat-pending-w': `${widths.pending}px`,
  }
}
