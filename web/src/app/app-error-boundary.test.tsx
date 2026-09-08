import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DICT } from '../i18n/dictionary'
import { LanguageProvider } from '../i18n/language-context'
import { AppErrorBoundary, RouteErrorBoundary } from './app-error-boundary'

let shouldThrow = true
function Bomb() {
  if (shouldThrow) throw new Error('payload rỗng')
  return <p>nội dung hub</p>
}

beforeEach(() => {
  shouldThrow = true
  // React logs the caught error itself; keep the test output readable.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

describe('RouteErrorBoundary', () => {
  it('replaces a crashed route with the recovery card and keeps the error text visible', () => {
    render(
      <LanguageProvider>
        <RouteErrorBoundary>
          <Bomb />
        </RouteErrorBoundary>
      </LanguageProvider>,
    )
    const card = screen.getByRole('alert')
    expect(card.textContent).toContain(DICT.vi['errorBoundary.title'])
    expect(card.textContent).toContain(DICT.vi['errorBoundary.hint'])
    expect(card.querySelector('.app-error-boundary-detail')?.textContent).toBe('payload rỗng')
    expect(screen.queryByText('nội dung hub')).toBeNull()
  })

  it('"Thử lại" re-renders the children; a crash that cleared shows the route again', () => {
    render(
      <LanguageProvider>
        <RouteErrorBoundary>
          <Bomb />
        </RouteErrorBoundary>
      </LanguageProvider>,
    )
    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: DICT.vi['errorBoundary.retry'] }))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('nội dung hub')).toBeTruthy()
  })

  it('"Tải lại trang" calls the reload hook instead of touching window.location in tests', () => {
    const onReload = vi.fn()
    render(
      <AppErrorBoundary
        labels={{ title: 't', hint: 'h', retry: 'r', reload: 'Tải lại trang' }}
        onReload={onReload}
      >
        <Bomb />
      </AppErrorBoundary>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Tải lại trang' }))
    expect(onReload).toHaveBeenCalledTimes(1)
  })

  it('renders children untouched when nothing throws', () => {
    shouldThrow = false
    render(
      <LanguageProvider>
        <RouteErrorBoundary>
          <Bomb />
        </RouteErrorBoundary>
      </LanguageProvider>,
    )
    expect(screen.getByText('nội dung hub')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
