// v96: the drag handles between the chat hub's columns, and the hook that owns the
// widths. Absolutely positioned over the grid gap, so adding them changes no grid
// track; the stylesheet hides each one at the breakpoint where its column folds away.
import { useCallback, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useLanguage } from '../../i18n/language-context'
import {
  KEYBOARD_STEP_PX,
  clampPaneWidth,
  draggedWidth,
  paneWidthVars,
  readPaneWidths,
  writePaneWidths,
  type PaneWidths,
  type ResizablePane,
} from './resizable-panes'

export interface PaneWidthsState {
  widths: PaneWidths
  /** Spread onto the grid element: the custom properties its columns read. */
  style: CSSProperties
  setWidth: (pane: ResizablePane, px: number) => void
}

export function usePaneWidths(): PaneWidthsState {
  const [widths, setWidths] = useState<PaneWidths>(readPaneWidths)
  const setWidth = useCallback((pane: ResizablePane, px: number) => {
    setWidths((prev) => {
      const next = { ...prev, [pane]: clampPaneWidth(pane, px) }
      writePaneWidths(next)
      return next
    })
  }, [])
  const style = useMemo(() => paneWidthVars(widths) as CSSProperties, [widths])
  return { widths, style, setWidth }
}

interface PaneResizerProps {
  pane: ResizablePane
  width: number
  onResize: (pane: ResizablePane, px: number) => void
}

export function PaneResizer({ pane, width, onResize }: PaneResizerProps) {
  const { t } = useLanguage()
  const drag = useRef<{ startX: number; startWidth: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    drag.current = { startX: e.clientX, startWidth: width }
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragging(true)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    onResize(pane, draggedWidth(pane, drag.current.startWidth, drag.current.startX, e.clientX))
  }
  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    setDragging(false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }
  // The separator is focusable: arrows move it without a mouse. The list handle sits
  // left of the thread, so → widens it; the pending handle is mirrored.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const sign = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (sign === 0) return
    e.preventDefault()
    onResize(pane, width + sign * KEYBOARD_STEP_PX * (pane === 'list' ? 1 : -1))
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={pane === 'list' ? t('chat.resizeList') : t('chat.resizePending')}
      aria-valuenow={width}
      tabIndex={0}
      className={`chat-resizer chat-resizer-${pane}${dragging ? ' is-dragging' : ''}`}
      data-testid={`chat-resizer-${pane}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
    />
  )
}
