import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { AppWalkthrough } from './app-walkthrough'
import {
  WALKTHROUGH_ANCHOR_CLASS,
  WALKTHROUGH_OPEN_EVENT,
  WALKTHROUGH_STEPS,
  WALKTHROUGH_STORAGE_KEY,
  readWalkthroughDone,
} from './walkthrough-state'

const store = new Map<string, string>()
beforeEach(() => {
  store.clear()
  document.body.innerHTML = ''
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

function mount() {
  // The anchors the shell would render.
  for (const s of WALKTHROUGH_STEPS) {
    const el = document.createElement('div')
    el.setAttribute('data-walkthrough', s.anchor)
    el.id = `anchor-${s.anchor}`
    document.body.appendChild(el)
  }
  return render(
    <LanguageProvider>
      <AppWalkthrough />
    </LanguageProvider>,
  )
}

describe('AppWalkthrough', () => {
  it('opens on a first visit, walks the four steps, highlights each anchor, remembers "done"', () => {
    mount()
    const card = screen.getByTestId('walkthrough')
    expect(card.getAttribute('data-step')).toBe('hubs')
    expect(card.textContent).toContain(DICT.vi['walkthrough.hubs.title'])
    expect(document.getElementById('anchor-hubs')?.classList.contains(WALKTHROUGH_ANCHOR_CLASS)).toBe(true)

    for (let i = 1; i < WALKTHROUGH_STEPS.length; i += 1) {
      fireEvent.click(screen.getByRole('button', { name: DICT.vi['walkthrough.next'] }))
      expect(card.getAttribute('data-step')).toBe(WALKTHROUGH_STEPS[i].id)
    }
    // The previous anchor lost its highlight, the current one has it.
    expect(document.getElementById('anchor-hubs')?.classList.contains(WALKTHROUGH_ANCHOR_CLASS)).toBe(false)
    expect(document.getElementById('anchor-shortcuts')?.classList.contains(WALKTHROUGH_ANCHOR_CLASS)).toBe(true)
    expect(screen.queryByRole('button', { name: DICT.vi['walkthrough.next'] })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: DICT.vi['walkthrough.done'] }))
    expect(screen.queryByTestId('walkthrough')).toBeNull()
    expect(store.get(WALKTHROUGH_STORAGE_KEY)).toBe('1')
    expect(readWalkthroughDone()).toBe(true)
    expect(document.getElementById('anchor-shortcuts')?.classList.contains(WALKTHROUGH_ANCHOR_CLASS)).toBe(false)
  })

  it('skip also remembers, and a done flag keeps it closed until re-opened by event', () => {
    const first = mount()
    fireEvent.click(screen.getByRole('button', { name: DICT.vi['walkthrough.skip'] }))
    expect(store.get(WALKTHROUGH_STORAGE_KEY)).toBe('1')
    first.unmount()

    mount()
    expect(screen.queryByTestId('walkthrough')).toBeNull()
    fireEvent(window, new Event(WALKTHROUGH_OPEN_EVENT))
    expect(screen.getByTestId('walkthrough').getAttribute('data-step')).toBe('hubs')
  })
})
