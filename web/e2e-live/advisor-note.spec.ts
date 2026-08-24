import { test, expect } from '@playwright/test'

/**
 * Runs against the REAL backend on 127.0.0.1:8765, not the mocked smoke suite.
 *
 * What it can assert deterministically is the room shell: it renders, and it renders
 * without a console error. It cannot assert that a specific advisor note is on screen —
 * the feed is a rolling window over live fleet events, so any particular note scrolls
 * out as work continues. Pinning one note's text made this fail hours later for a
 * reason that was not a regression.
 *
 * The advisor kind's own rendering is pinned deterministically in
 * `src/features/shared/office-message-line.test.ts`; what this adds is proof that the
 * real server serves a room the real browser can mount.
 */
test('the office room mounts against the live backend without console errors', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  const room = process.env.LIVE_ROOM_ID ?? 'office'
  await page.goto(`/office?room=${room}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  await page.screenshot({ path: 'test-results/live-office-room.png', fullPage: true })

  const body = await page.locator('body').innerText()
  console.log('URL:', page.url())
  console.log('ADVISOR LINES:', (body.match(/Cố vấn/g) ?? []).length)
  console.log('ERRORS:', errors.join(' | ') || '(none)')

  expect(errors, 'no console errors').toEqual([])
  expect(body.length, 'room rendered content').toBeGreaterThan(0)
})
