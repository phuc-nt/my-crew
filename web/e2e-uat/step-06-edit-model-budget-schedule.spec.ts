import { test, expect } from '@playwright/test'
import { login } from './uat-login'

/**
 * UAT step 6: change model + monthly budget cap + schedule through the FORM only, then
 * prove the profile.yaml on disk changed in the right place and kept its comments.
 *
 * The point is not that a PATCH works — unit tests cover that. It is that a
 * non-technical operator can retune an agent without opening an editor, and that doing
 * so does not shred the heavily-commented file the repo ships. `profile.yaml` for
 * `default` is ~100 lines of which most are explanatory comments; a naive
 * load-then-dump would erase all of them.
 */
const AGENT = 'default'
const NEW_MODEL = 'anthropic/claude-3.5-haiku'
const NEW_CAP = '77'
const NEW_SCHEDULE = 'weekly_report = 0 9 * * 1'

test('model, budget cap and schedule are editable from the form without touching YAML', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await login(page)

  // Baseline straight from the API the form reads, so the assertions below compare
  // against what the operator actually saw, not against an assumption.
  const before = await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()
  console.log('BEFORE:', JSON.stringify({
    model: before.model, cap: before.budget_monthly_usd, schedule: before.schedule,
  }))

  await page.goto(`/team/${AGENT}`, { waitUntil: 'domcontentloaded' })

  let clicks = 0

  // --- Model: Hồ sơ tab, inline row keyed by its <dt> label -----------------------
  await page.getByRole('button', { name: 'Hồ sơ' }).click(); clicks++
  await expect(page.locator('.agent-profile-facts')).toContainText('Model', { timeout: 30_000 })
  // Each InlineEditRow renders its own "Sửa" chip; scope to the one following the
  // Model <dt> so this cannot silently edit the wrong field.
  await page.locator('dt', { hasText: /^Model$/ }).locator('xpath=following-sibling::dd[1]')
    .getByRole('button', { name: 'Sửa' }).click(); clicks++
  await page.getByPlaceholder('vendor/model-name').fill(NEW_MODEL)
  await page.getByRole('button', { name: 'Lưu' }).first().click(); clicks++
  await expect(page.locator('.agent-profile-facts')).toContainText(NEW_MODEL, { timeout: 30_000 })
  console.log('MODEL SET:', NEW_MODEL)

  // --- Schedule: same tab -------------------------------------------------------
  await page.locator('dt', { hasText: /^Lịch chạy$/ }).locator('xpath=following-sibling::dd[1]')
    .getByRole('button', { name: 'Sửa' }).click(); clicks++
  await page.getByPlaceholder('weekly_report = 0 9 * * 1').fill(NEW_SCHEDULE)
  await page.getByRole('button', { name: 'Lưu' }).first().click(); clicks++
  await expect(page.locator('.agent-profile-facts')).toContainText('weekly_report', { timeout: 30_000 })
  console.log('SCHEDULE SET:', NEW_SCHEDULE)

  // --- Budget cap: its own tab --------------------------------------------------
  await page.getByRole('button', { name: 'Ngân sách & chi phí' }).click(); clicks++
  await page.getByRole('button', { name: 'Sửa' }).first().click(); clicks++
  await page.locator('input[type=number]').first().fill(NEW_CAP)
  await page.getByRole('button', { name: 'Lưu' }).first().click(); clicks++
  console.log('CAP SET:', NEW_CAP)

  // --- The API must agree ---------------------------------------------------------
  await expect.poll(async () => {
    const s = await (await page.request.get(`/api/agents/${AGENT}/profile-settings`)).json()
    return `${s.model}|${s.budget_monthly_usd}|${JSON.stringify(s.schedule)}`
  }, { timeout: 30_000, message: 'all three edits must be readable back' })
    .toBe(`${NEW_MODEL}|${Number(NEW_CAP)}|{"weekly_report":"0 9 * * 1"}`)

  // --- And the FILE must have changed in the right region, comments intact ---------
  const raw = await (await page.request.get(`/api/agents/${AGENT}/config`)).json()
  const yaml: string = raw.files?.profile ?? ''
  expect(yaml, 'config readback must return profile.yaml').toContain('name: default')

  // New values landed.
  expect(yaml).toContain(`model: ${NEW_MODEL}`)
  expect(yaml).toContain(`monthly_usd: ${NEW_CAP}`)
  expect(yaml).toContain('weekly_report')

  // Comments survived — sample one from each region of the file, so a wipe anywhere
  // is caught rather than just a wipe at the top.
  for (const comment of [
    'token_env holds env-var NAMES, never tokens.',
    'BUDGET_WARN_RATIO',
    'DRY_RUN  (v1 default true)',
    'PR_STALE_DAYS',
    'one shared Atlassian token in M1',
    'Token value lives in .env only.',
  ]) {
    expect(yaml, `comment must survive the edit: ${comment}`).toContain(comment)
  }

  // Untouched values must not have drifted.
  expect(yaml).toContain('warn_ratio: 0.8')
  expect(yaml).toContain('pr_stale_days: 7')

  console.log('EDIT CLICKS:', clicks)
  console.log('YAML LINES:', yaml.split('\n').length)
  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
  expect(errors.filter(e => !/401/.test(e)), 'no unexpected console errors').toEqual([])
})
