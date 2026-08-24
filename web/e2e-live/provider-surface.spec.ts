import { test, expect } from '@playwright/test'

/**
 * v91 live: a provider-prefixed chain entry (`provider::model`) must survive the whole
 * round trip — textarea → PATCH → profile.yaml → GET → rendered cell. The `::` is the
 * one character the surface could plausibly mangle (validators that split on `:` would),
 * and a mangled prefix routes real work to the wrong vendor.
 *
 * Runs against the REAL backend on 127.0.0.1:8765. Restores the agent's original
 * role_models on the way out — a stray override silently bills later runs.
 */
const AGENT = 'analyst'
const ENTRY = 'altroute::deepseek/deepseek-v4-pro-0813'

function valueCell(page: import('@playwright/test').Page, label: string) {
  return page.locator('dl.agent-profile-facts dt', { hasText: label }).first()
    .locator('xpath=following-sibling::dd[1]')
}

test('a provider-prefixed role model round-trips through the real form', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await page.goto(`/team/${AGENT}?tab=profile`, { waitUntil: 'domcontentloaded' })

  const roleCell = valueCell(page, 'Model theo loại việc')
  await expect(roleCell).toBeVisible({ timeout: 15_000 })

  // The prefix the live fleet is already routing through must be what the form shows.
  await expect(roleCell).toContainText(ENTRY)

  // Type a SECOND prefixed entry: the `::` must survive parse + write, not just display.
  await roleCell.getByText('Sửa').click()
  await roleCell.locator('textarea').fill(`content = ${ENTRY}\nreview = ${ENTRY}`)
  await roleCell.getByText('Lưu').click()
  await expect(roleCell).toContainText('review', { timeout: 15_000 })

  const written = await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()
  expect(written.role_models).toEqual({ content: ENTRY, review: ENTRY })

  // Restore: back to content-only, which is what the live routing test relies on.
  await roleCell.getByText('Sửa').click()
  await roleCell.locator('textarea').fill(`content = ${ENTRY}`)
  await roleCell.getByText('Lưu').click()
  await expect
    .poll(async () => (await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()).role_models,
          { timeout: 15_000 })
    .toEqual({ content: ENTRY })

  expect(errors, 'no console errors').toEqual([])
})
