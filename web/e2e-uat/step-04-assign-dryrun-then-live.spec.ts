import { test, expect } from '@playwright/test'
import { login } from './uat-login'

/**
 * UAT step 4: assign real work, see the rehearsal badge, turn rehearsal off from the
 * agent page, reassign, and get a REAL delivery.
 *
 * The point of the step is the safety posture: a freshly hired agent ships with
 * `dry_run: true`, so the CEO's first assignment rehearses instead of messaging the
 * outside world. Going live must be a deliberate, visible act — and the plan budgets
 * exactly 2 clicks for it, so this test counts them.
 */
/** Who ROUTES the work. Deliberately NOT assignable — `assignable_staff` excludes the
 *  coordinator and admin, so naming them as PIC is rejected. */
const COORDINATOR = 'coordinator'
/** Who DOES the work: the seeded pm agent, the only worker a fresh home ships with. */
const AGENT = 'default'
const BRIEF = `@${AGENT} Nhắn cho sếp một câu chào ngắn qua Telegram, đúng 1 câu.`

test('assign shows the dry-run badge, then goes live in 2 clicks', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  // Surface the API's own words — a 400 here otherwise shows up only as a silent
  // never-appearing preview.
  page.on('response', async r => {
    if (r.url().includes('/api/office/assign/') && r.status() >= 400) {
      console.log('ASSIGN API', r.status(), await r.text().catch(() => '<no body>'))
    }
  })

  await login(page)

  // The hire must still be rehearsing — that is the precondition the badge reports on.
  const before = await (await page.request.get(`/api/agents/${AGENT}/safety`)).json()
  expect(before.dry_run, 'a fresh hire must default to rehearsal').toBe(true)

  // --- 0. appoint the coordinator ---
  // Hiring a coordinator-template agent does NOT appoint them: the fleet keeps an empty
  // `coordinator_id` and the Office refuses all work until someone fills it in on a
  // different hub. Walk that real path here rather than patching company.yaml directly.
  const company = await (await page.request.get('/api/company')).json()
  if (!company.coordinator_id) {
    await page.goto('/system', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Công ty' }).click()
    const coordInput = page.locator('.company-identity label', { hasText: 'Điều phối viên' })
      .locator('input')
    await coordInput.fill(COORDINATOR)
    await page.locator('.company-identity').getByRole('button', { name: 'Lưu' }).click()
    await expect(page.locator('.company-identity')).toContainText('Đã lưu', { timeout: 20_000 })

    const saved = await (await page.request.get('/api/company')).json()
    expect(saved.coordinator_id, 'the appointment must persist').toBe(COORDINATOR)
    console.log('APPOINTED:', COORDINATOR, 'as coordinator')
  }

  // --- 0b. switch the hire on ---
  // Template hires are created disabled on purpose, so credentials land in .env before the
  // agent can ever run. "Bật lại" is the step that undoes it (it clears BOTH the registry
  // and profile gates), and until then the agent is not on the assignable roster.
  const roster = await (await page.request.get('/api/agents')).json()
  if (!roster.find((a: any) => a.id === AGENT)?.enabled) {
    await page.goto('/team', { waitUntil: 'domcontentloaded' })
    await page.locator('tr', { hasText: AGENT }).getByRole('button', { name: 'Bật lại' }).click()
    await expect(page.locator('tr', { hasText: AGENT })).toContainText('✓ bật', { timeout: 20_000 })
    console.log('ENABLED:', AGENT)
  }

  // --- 1. assign while rehearsing: the badge must appear BEFORE any confirm ---
  // Giao việc lives in the chat hub; Office only carries a modal shortcut into it.
  await page.goto('/chat', { waitUntil: 'domcontentloaded' })
  const composer = page.locator('.office-composer')
  await expect(composer).toBeVisible({ timeout: 20_000 })
  await composer.locator('input[type=text]').fill(BRIEF)
  await composer.getByRole('button', { name: 'Giao việc' }).click()

  await expect(composer.locator('.office-composer-preview')).toBeVisible({ timeout: 240_000 })
  await expect(
    composer.locator('.office-dry-run-badge'),
    'a rehearsing PIC must be flagged before the CEO confirms',
  ).toBeVisible()
  console.log('DRY-RUN BADGE shown on preview')

  await composer.getByRole('button', { name: 'Huỷ' }).click()

  // --- 2. turn rehearsal off from the agent page, counting real clicks ---
  await page.goto(`/team/${AGENT}`, { waitUntil: 'domcontentloaded' })
  let clicks = 0
  await page.getByRole('button', { name: 'Hồ sơ' }).click(); clicks++
  await page.getByRole('checkbox', { name: /Diễn tập/ }).click(); clicks++
  await expect(page.locator('.agent-dry-run-toggle').first()).toContainText('Gửi thật', { timeout: 15_000 })
  console.log('WENT LIVE in', clicks, 'clicks')
  expect(clicks, 'the plan budgets 2 clicks to leave rehearsal').toBeLessThanOrEqual(2)

  // It must be persisted, not just optimistic local state.
  const after = await (await page.request.get(`/api/agents/${AGENT}/safety`)).json()
  expect(after.dry_run, 'going live must persist').toBe(false)
  expect(after.dry_run_source, 'the override belongs to this agent').toBe('profile')

  // --- 3. reassign: the badge must be gone, and the work must really run ---
  await page.goto('/chat', { waitUntil: 'domcontentloaded' })
  await expect(composer).toBeVisible({ timeout: 20_000 })
  await composer.locator('input[type=text]').fill(BRIEF)
  await composer.getByRole('button', { name: 'Giao việc' }).click()
  await expect(composer.locator('.office-composer-preview')).toBeVisible({ timeout: 240_000 })
  await expect(
    composer.locator('.office-dry-run-badge'),
    'a live PIC must NOT be flagged as rehearsing',
  ).toHaveCount(0)

  await composer.getByRole('button', { name: 'Xác nhận giao việc' }).click()
  await expect(composer.locator('.office-composer-done, .office-composer-preview'))
    .toBeVisible({ timeout: 180_000 })
  console.log('ASSIGNED live:', (await composer.innerText()).slice(0, 300).replace(/\n+/g, ' | '))

  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
  expect(errors.filter(e => !/401/.test(e)), 'no unexpected console errors').toEqual([])
})
