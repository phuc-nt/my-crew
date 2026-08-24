import { test, expect } from '@playwright/test'

// UAT step 1: pip install → my-crew serve → open web. The wizard MUST appear on a
// home that has never been configured; a blank page or a login form would mean a
// new operator is dead in the water with no way forward.
test('a never-configured home lands on the setup wizard', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await page.goto('/', { waitUntil: 'domcontentloaded' })

  // Whatever the wizard is called, it must ask for the one thing setup needs.
  await expect(page.locator('body')).toContainText(/OpenRouter/i, { timeout: 30_000 })

  console.log('URL:', page.url())
  console.log('HEADINGS:', (await page.locator('h1, h2').allTextContents()).join(' | '))
  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
})
