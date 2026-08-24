import { expect, type Page } from '@playwright/test'

/** The credential the wizard set in step 2. Defaulted here rather than hardcoded per
 *  spec, so a run against a differently-seeded home only has to set one variable.
 *  This is a throwaway local fixture, never a real account. */
export const UAT_PASSWORD = process.env.UAT_PASSWORD ?? 'uat-Passw0rd!2026'

/** Shared UAT login. The wizard set these in step 2; every later step starts logged out. */
export async function login(page: Page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)
  const fields = await page.locator('input:visible').all()
  if (fields.length >= 2) {
    await fields[0].fill('admin')
    await fields[1].fill(UAT_PASSWORD)
    await page.getByRole('button', { name: 'Đăng nhập' }).click()
    await expect(page.locator('body')).toContainText('Đội ngũ', { timeout: 20_000 })
  }
}
