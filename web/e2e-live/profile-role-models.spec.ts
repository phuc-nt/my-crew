import { test, expect } from '@playwright/test'

/**
 * Runs against the REAL backend on 127.0.0.1:8765 with a real profiles/<id>/profile.yaml
 * on disk — no page.route mocks. What it proves that the unit suite cannot: the form the
 * browser renders, the payload it sends, and the yaml the server writes agree end to end.
 *
 * The agent it edits is taken from LIVE_SETTINGS_AGENT (default `qa`). It leaves the
 * agent's role_models cleared, since an override left behind would silently bill later
 * runs on whatever model this test happened to type.
 */
const AGENT = process.env.LIVE_SETTINGS_AGENT ?? 'qa'

/** The <dd> cell of the fact row whose <dt> label matches. Positional indices retarget
 *  silently the moment a row is added above, which is exactly what this phase did. */
function valueCell(page: import('@playwright/test').Page, label: string) {
  return page.locator('dl.agent-profile-facts dt', { hasText: label }).first()
    .locator('xpath=following-sibling::dd[1]')
}

test('role_models and the advisor toggle round-trip through the real form', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await page.goto(`/team/${AGENT}?tab=profile`, { waitUntil: 'domcontentloaded' })

  const roleCell = valueCell(page, 'Model theo loại việc')
  await expect(roleCell).toBeVisible({ timeout: 15_000 })

  // 1. A rejected role name must surface the BACKEND's own message, not a web-layer copy.
  await roleCell.getByText('Sửa').click()
  await roleCell.locator('textarea').fill('reviewer = vendor/x')
  await roleCell.getByText('Lưu').click()
  await expect(roleCell.locator('.error')).toContainText('unknown role_models key', { timeout: 15_000 })

  // 2. A valid map writes through to the yaml the loader reads.
  await roleCell.locator('textarea').fill('review = google/gemini-3-flash')
  await roleCell.getByText('Lưu').click()
  await expect(roleCell).toContainText('review', { timeout: 15_000 })
  await expect(roleCell).toContainText('google/gemini-3-flash')

  const written = await page.request.get(`/api/agents/${AGENT}/profile-settings`)
  expect((await written.json()).role_models).toEqual({ review: 'google/gemini-3-flash' })

  // 3. The advisor toggle flips the real runtime.advisor_enabled key.
  const advisorCell = valueCell(page, 'Cố vấn theo sát')
  const before = (await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()).advisor_enabled
  await advisorCell.getByRole('checkbox').click()
  await expect
    .poll(async () => (await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()).advisor_enabled,
          { timeout: 15_000 })
    .toBe(!before)
  await expect(advisorCell).toContainText(!before ? 'Bật' : 'Tắt')

  // 4. Clearing the textarea removes every override — the silent-billing failure mode.
  await roleCell.getByText('Sửa').click()
  await roleCell.locator('textarea').fill('')
  await roleCell.getByText('Lưu').click()
  await expect
    .poll(async () => (await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()).role_models,
          { timeout: 15_000 })
    .toEqual({})

  await page.screenshot({ path: 'test-results/live-profile-settings.png', fullPage: true })
  // Step 1 deliberately sends a payload the backend must reject, and the browser logs
  // every non-2xx as a console error. That one is the test working; anything else is not.
  const unexpected = errors.filter(e => !/400 \(Bad Request\)/.test(e))
  expect(unexpected, 'no unexpected console errors').toEqual([])
})
