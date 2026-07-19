import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './fonts.css'
import './index.css'
import App from './App.tsx'
import { LanguageProvider } from './i18n/language-context.tsx'
import { ThemeProvider } from './theme-context.tsx'
import { UiModeProvider } from './ui-mode-context.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <LanguageProvider>
        <UiModeProvider>
          <App />
        </UiModeProvider>
      </LanguageProvider>
    </ThemeProvider>
  </StrictMode>,
)
