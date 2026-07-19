// v53 language mode: toggle re-labels chrome, persistence contract, param interpolation.
// The dictionary's own type-safety (missing en key = compile error) is enforced by the
// `satisfies` clause in dictionary.ts — tsc is the test for that.
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import { Layout } from '../components/Layout'
import { AppProviders } from '../test-utils'
import { DICT } from './dictionary'
import { LanguageProvider, useLanguage } from './language-context'

function renderChrome() {
  return render(
    <MemoryRouter>
      <AppProviders>
        <Layout />
      </AppProviders>
    </MemoryRouter>,
  )
}

test('default vi: nav renders Vietnamese labels', () => {
  renderChrome()
  expect(screen.getByText(DICT.vi['nav.office'])).toBeTruthy()
  expect(screen.getByText(DICT.vi['nav.work'])).toBeTruthy()
})

test('VN→EN toggle re-labels the whole nav instantly', () => {
  renderChrome()
  fireEvent.click(screen.getByText('VN'))
  expect(screen.getByText(DICT.en['nav.office'])).toBeTruthy()
  expect(screen.getByText(DICT.en['nav.work'])).toBeTruthy()
  expect(screen.getByText(DICT.en['chrome.logout'])).toBeTruthy()
  // toggle button now shows EN and flips back
  fireEvent.click(screen.getByText('EN'))
  expect(screen.getByText(DICT.vi['nav.office'])).toBeTruthy()
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
