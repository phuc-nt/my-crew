import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import {
  DEFAULT_PANE_WIDTHS,
  KEYBOARD_STEP_PX,
  PANE_LIMITS,
  PANE_WIDTHS_STORAGE_KEY,
  clampPaneWidth,
  draggedWidth,
  paneWidthVars,
  readPaneWidths,
  writePaneWidths,
} from './resizable-panes'
import { PaneResizer } from './resizable-panes.tsx'

const store = new Map<string, string>()
beforeEach(() => {
  store.clear()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size
    },
  })
})

describe('pane width arithmetic', () => {
  it('clamps to the pane limits and falls back to the default on garbage', () => {
    expect(clampPaneWidth('list', 50)).toBe(PANE_LIMITS.list.min)
    expect(clampPaneWidth('list', 9999)).toBe(PANE_LIMITS.list.max)
    expect(clampPaneWidth('pending', 300.4)).toBe(300)
    expect(clampPaneWidth('pending', NaN)).toBe(DEFAULT_PANE_WIDTHS.pending)
  })

  it('the list grows with a rightward drag, the pending pane with a leftward one', () => {
    expect(draggedWidth('list', 280, 100, 160)).toBe(340)
    expect(draggedWidth('list', 280, 100, 40)).toBe(220)
    expect(draggedWidth('pending', 300, 900, 840)).toBe(360)
    expect(draggedWidth('pending', 300, 900, 960)).toBe(240)
    // Past the limit the width pins, however far the pointer goes.
    expect(draggedWidth('list', 280, 100, 1000)).toBe(PANE_LIMITS.list.max)
  })

  it('persists and re-reads the widths, clamping whatever was stored', () => {
    expect(readPaneWidths()).toEqual(DEFAULT_PANE_WIDTHS)
    writePaneWidths({ list: 320, pending: 260 })
    expect(readPaneWidths()).toEqual({ list: 320, pending: 260 })
    store.set(PANE_WIDTHS_STORAGE_KEY, JSON.stringify({ list: 5, pending: 'x' }))
    expect(readPaneWidths()).toEqual({ list: PANE_LIMITS.list.min, pending: DEFAULT_PANE_WIDTHS.pending })
    store.set(PANE_WIDTHS_STORAGE_KEY, '{oops')
    expect(readPaneWidths()).toEqual(DEFAULT_PANE_WIDTHS)
    expect(paneWidthVars({ list: 320, pending: 260 })).toEqual({
      '--chat-list-w': '320px',
      '--chat-pending-w': '260px',
    })
  })
})

describe('PaneResizer', () => {
  it('reports the dragged width from pointer events and nudges with the arrow keys', () => {
    const onResize = vi.fn()
    render(
      <LanguageProvider>
        <PaneResizer pane="list" width={280} onResize={onResize} />
      </LanguageProvider>,
    )
    const handle = screen.getByRole('separator', { name: DICT.vi['chat.resizeList'] })
    expect(handle.getAttribute('aria-valuenow')).toBe('280')
    // jsdom has no pointer capture; the handle must not depend on it.
    Object.assign(handle, {
      setPointerCapture: () => undefined,
      hasPointerCapture: () => false,
      releasePointerCapture: () => undefined,
    })
    fireEvent.pointerDown(handle, { button: 0, clientX: 100, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 150, pointerId: 1 })
    expect(onResize).toHaveBeenLastCalledWith('list', 330)
    expect(handle.className).toContain('is-dragging')
    fireEvent.pointerUp(handle, { pointerId: 1 })
    expect(handle.className).not.toContain('is-dragging')
    // After release a stray move changes nothing.
    fireEvent.pointerMove(handle, { clientX: 400, pointerId: 1 })
    expect(onResize).toHaveBeenCalledTimes(1)

    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(onResize).toHaveBeenLastCalledWith('list', 280 + KEYBOARD_STEP_PX)
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(onResize).toHaveBeenLastCalledWith('list', 280 - KEYBOARD_STEP_PX)
  })

  it('mirrors the arrow keys for the pending pane, which sits right of its handle', () => {
    const onResize = vi.fn()
    render(
      <LanguageProvider>
        <PaneResizer pane="pending" width={300} onResize={onResize} />
      </LanguageProvider>,
    )
    const handle = screen.getByRole('separator', { name: DICT.vi['chat.resizePending'] })
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(onResize).toHaveBeenLastCalledWith('pending', 300 + KEYBOARD_STEP_PX)
  })
})
