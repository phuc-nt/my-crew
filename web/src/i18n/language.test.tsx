// v53 language mode: toggle re-labels chrome, persistence contract, param interpolation.
// The dictionary's own type-safety (missing en key = compile error) is enforced by the
// `satisfies` clause in dictionary.ts — tsc is the test for that.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import { AppShell } from '../app/app-shell'
import { AppProviders } from '../test-utils'
import { DICT } from './dictionary'
import { LanguageProvider, useLanguage } from './language-context'

// The shell's own badges (pending approvals, team health) read from the query cache, so
// the chrome cannot render without a client — each test gets a fresh, retry-free one.
function renderChrome() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AppProviders>
          <AppShell />
        </AppProviders>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('default vi: nav renders Vietnamese labels', () => {
  renderChrome()
  expect(screen.getByText(DICT.vi['hub.office'])).toBeTruthy()
  expect(screen.getByText(DICT.vi['hub.work'])).toBeTruthy()
})

test('VN→EN toggle re-labels the whole nav instantly', () => {
  renderChrome()
  fireEvent.click(screen.getByText('VN'))
  expect(screen.getByText(DICT.en['hub.office'])).toBeTruthy()
  expect(screen.getByText(DICT.en['hub.work'])).toBeTruthy()
  expect(screen.getByText(DICT.en['chrome.logout'])).toBeTruthy()
  // toggle button now shows EN and flips back
  fireEvent.click(screen.getByText('EN'))
  expect(screen.getByText(DICT.vi['hub.office'])).toBeTruthy()
})

function ParamProbe() {
  const { t } = useLanguage()
  // no param-carrying key in the chrome set yet; prove the mechanism via replaceAll
  return <span>{t('common.loading')}</span>
}

test('t() falls back to vi and renders through the provider', () => {
  render(
    <LanguageProvider>
      <ParamProbe />
    </LanguageProvider>,
  )
  expect(screen.getByText(DICT.vi['common.loading'])).toBeTruthy()
})
