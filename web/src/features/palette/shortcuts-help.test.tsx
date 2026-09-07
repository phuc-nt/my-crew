// `?` toggles the card, Escape closes it, `g`+letter jumps hubs, and none of it fires
// while the CEO is typing in a field.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { expect, test } from 'vitest'
import { AppProviders } from '../../test-utils'
import { SHORTCUTS_OPEN_EVENT, ShortcutsHelp } from './shortcuts-help'

function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="loc">{loc.pathname}</span>
}

function renderHelp() {
  return render(
    <MemoryRouter initialEntries={['/chat']}>
      <AppProviders>
        <ShortcutsHelp />
        <input aria-label="ô gõ" />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </AppProviders>
    </MemoryRouter>,
  )
}

test('? opens the card listing every chord; Escape closes it', () => {
  renderHelp()
  expect(screen.queryByTestId('shortcuts-help')).toBeNull()
  fireEvent.keyDown(window, { key: '?' })
  const card = screen.getByTestId('shortcuts-help')
  expect(card.textContent).toContain('Mở bảng lệnh')
  expect(card.textContent).toContain('Tới Công việc')
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.queryByTestId('shortcuts-help')).toBeNull()
})

test('g then a hub letter navigates; a stale g does not', () => {
  renderHelp()
  fireEvent.keyDown(window, { key: 'g' })
  fireEvent.keyDown(window, { key: 'w' })
  expect(screen.getByTestId('loc')).toHaveTextContent('/work')
  // A letter on its own is not a chord.
  fireEvent.keyDown(window, { key: 't' })
  expect(screen.getByTestId('loc')).toHaveTextContent('/work')
  // Modifier chords belong to the browser / palette.
  fireEvent.keyDown(window, { key: 'g' })
  fireEvent.keyDown(window, { key: 's', metaKey: true })
  expect(screen.getByTestId('loc')).toHaveTextContent('/work')
})

test('keys typed into a field are left alone; the header event still opens the card', () => {
  renderHelp()
  const input = screen.getByLabelText('ô gõ')
  fireEvent.keyDown(input, { key: '?' })
  expect(screen.queryByTestId('shortcuts-help')).toBeNull()
  fireEvent.keyDown(input, { key: 'g' })
  fireEvent.keyDown(input, { key: 'w' })
  expect(screen.getByTestId('loc')).toHaveTextContent('/chat')
  act(() => {
    window.dispatchEvent(new Event(SHORTCUTS_OPEN_EVENT))
  })
  expect(screen.getByTestId('shortcuts-help')).toBeTruthy()
})
