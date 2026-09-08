import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { DICT } from '../i18n/dictionary'
import { LanguageProvider } from '../i18n/language-context'
import { UpdateAvailableBanner } from './update-available-banner'

function renderBanner(pollMs = 20) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider>
        <UpdateAvailableBanner pollMs={pollMs} />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('UpdateAvailableBanner', () => {
  it('stays hidden while /health keeps reporting the version the tab started with', async () => {
    const spy = vi.spyOn(api, 'getHealth').mockResolvedValue({ ok: true, version: '0.18.0' })
    renderBanner()
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2))
    expect(screen.queryByTestId('update-banner')).toBeNull()
  })

  it('appears once a later poll reports a different version, names it, and "Để sau" hides it', async () => {
    const versions = ['0.18.0', '0.18.0', '0.19.0']
    vi.spyOn(api, 'getHealth').mockImplementation(async () => ({
      ok: true,
      version: versions.length > 1 ? (versions.shift() as string) : versions[0],
    }))
    renderBanner()
    const banner = await screen.findByTestId('update-banner')
    expect(banner.textContent).toContain(
      DICT.vi['updateBanner.text'].replace('{version}', '0.19.0'),
    )
    fireEvent.click(screen.getByRole('button', { name: DICT.vi['updateBanner.dismiss'] }))
    expect(screen.queryByTestId('update-banner')).toBeNull()
    // Still dismissed on the next poll of the SAME version.
    await new Promise((r) => setTimeout(r, 60))
    expect(screen.queryByTestId('update-banner')).toBeNull()
  })

  it('ignores a poll with no version (an older backend) instead of treating it as a change', async () => {
    const spy = vi.spyOn(api, 'getHealth').mockResolvedValue({ ok: true })
    renderBanner()
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2))
    expect(screen.queryByTestId('update-banner')).toBeNull()
  })
})
