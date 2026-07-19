// Shared test render helper (v10 M25): wraps a UI tree in the app-level providers that many
// views now consume (theme + ui-mode). Keeps individual tests from having to know the provider
// stack. Router is NOT included — tests that need routing add their own MemoryRouter.
import { render } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { LanguageProvider } from './i18n/language-context'
import { ThemeProvider } from './theme-context'
import { UiModeProvider } from './ui-mode-context'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <UiModeProvider>{children}</UiModeProvider>
      </LanguageProvider>
    </ThemeProvider>
  )
}

export function renderWithProviders(ui: ReactElement) {
  return render(<AppProviders>{ui}</AppProviders>)
}
