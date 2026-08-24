import { test, expect } from '@playwright/test'

const NOTE = 'không cùng hạng'

test('advisor note reaches the office room in a real browser', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await page.goto('/office?room=7ec23d4af7b9', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  await page.screenshot({ path: 'test-results/live-office-room.png', fullPage: true })

  const body = await page.locator('body').innerText()
  const idx = body.indexOf(NOTE)
  console.log('URL:', page.url())
  console.log('ADVISOR NOTE VISIBLE:', idx >= 0)
  console.log('CONTEXT:\n' + (idx >= 0 ? body.slice(Math.max(0, idx - 600), idx + 200) : body.slice(0, 1800)))
  console.log('ERRORS:', errors.join(' | ') || '(none)')
  expect(errors, 'no console errors').toEqual([])
  expect(idx, 'advisor note rendered in the room').toBeGreaterThanOrEqual(0)
})
