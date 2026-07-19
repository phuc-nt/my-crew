// v10 M26: the health panel summarizes pass/fail and renders a backtick command in a hint as a
// copy-paste <code>. Mocked api.
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { IntegrationHealthPanel } from './IntegrationHealthPanel'

beforeEach(() => vi.restoreAllMocks())

function renderPanel() {
  return render(
    <LanguageProvider>
      <IntegrationHealthPanel />
    </LanguageProvider>,
  )
}

test('renders a failing check hint with a backtick command as <code>', async () => {
  vi.spyOn(api, 'getIntegrationHealth').mockResolvedValue({
    checked_at: 0,
    checks: [
      { id: 'gh', label: 'GitHub CLI', ok: false, detail: 'not authed', hint: 'Run `gh auth login` once' },
      { id: 'openrouter', label: 'OpenRouter (LLM)', ok: true, detail: 'set', hint: '' },
    ],
  })
  renderPanel()
  await waitFor(() => expect(screen.getByText('GitHub CLI')).toBeInTheDocument())
  // the command inside backticks becomes a code element with the exact command text
  const code = screen.getByText('gh auth login')
  expect(code.tagName).toBe('CODE')
  // summary reflects the one failing check
  expect(screen.getByText(/1 mục cần khắc phục/)).toBeInTheDocument()
})

test('shows an all-ready summary when nothing fails', async () => {
  vi.spyOn(api, 'getIntegrationHealth').mockResolvedValue({
    checked_at: 0,
    checks: [{ id: 'openrouter', label: 'OpenRouter (LLM)', ok: true, detail: 'set', hint: '' }],
  })
  renderPanel()
  await waitFor(() => expect(screen.getByText(/Tất cả kết nối đều sẵn sàng/)).toBeInTheDocument())
})
