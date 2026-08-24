import { test, expect } from '@playwright/test'
import { UAT_PASSWORD } from './uat-login'

/**
 * UAT step 2: walk the ENTIRE wizard with a real OpenRouter key, a real password and a
 * real operator email, then check what the finish screen says about restarting.
 *
 * The claim under test is narrow and was a P1 fix: the finish screen must not fake a
 * restart ("Restarting…" with a spinner that never returns). A serve process cannot
 * restart itself; telling the operator it is doing so strands them on a dead page.
 */
const KEY = process.env.OPENROUTER_API_KEY!
const PASSWORD = UAT_PASSWORD
const EMAIL = 'uat-operator@example.com'

test('the wizard completes and tells the truth about restarting', async ({ page }) => {
  test.skip(!KEY, 'needs OPENROUTER_API_KEY')
  let finishBody: { restarting: boolean; restart_hint: string; message: string } | null = null
  page.on('response', async r => {
    if (r.url().includes('/api/setup/finish') && r.status() === 200) {
      try { finishBody = await r.json() } catch { /* body already consumed */ }
    }
  })
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await page.goto('/', { waitUntil: 'domcontentloaded' })

  // Step 1/7 — the OpenRouter key, verified against the real API by the app itself.
  await page.locator('input[type=password]').fill(KEY)
  await page.getByRole('button', { name: 'Kiểm tra kết nối' }).click()
  await expect(page.locator('body')).not.toContainText(/thất bại|không hợp lệ/i, { timeout: 30_000 })
  await page.getByRole('button', { name: 'Tiếp tục' }).click()

  // Walk the remaining screens generically: fill what each asks for, then advance.
  for (let guard = 0; guard < 12; guard++) {
    await page.waitForTimeout(600)
    const body = await page.locator('body').innerText()
    const stepLabel = body.match(/Bước \d+\/\d+/)?.[0] ?? '(no step label)'
    console.log(`\n=== ${stepLabel} :: ${(await page.locator('h1,h2,h3').allTextContents()).join(' | ')}`)
    console.log(body.slice(0, 500))

    // Fill any visible empty field with something plausible for its kind.
    for (const input of await page.locator('input:visible').all()) {
      if (await input.inputValue()) continue
      const type = await input.getAttribute('type')
      const near = (await input.getAttribute('placeholder')) ?? ''
      if (type === 'password') await input.fill(PASSWORD)
      else if (type === 'email' || /email|mail/i.test(near + body)) await input.fill(EMAIL)
      else if (type === 'checkbox') { /* leave defaults */ }
      else await input.fill(EMAIL)
    }

    const next = page.getByRole('button', { name: /Tiếp tục|Hoàn tất|Xong|Bắt đầu|Lưu/ })
    if (!(await next.count())) break
    await next.first().click()
  }

  await page.waitForTimeout(2500)
  const finish = await page.locator('body').innerText()
  console.log('\n=== FINISH SCREEN ===\n' + finish.slice(0, 1500))

  // The honesty check, asserted on the API's own answer rather than a screen that moves
  // on: this instance is NOT the launchd-managed service, so it must report restarting
  // false and hand back a hint naming the manual path. Claiming a self-restart here
  // would strand the operator on a page that never comes back — and the fix that makes
  // this true also stops it kickstarting a DIFFERENT installation's service.
  expect(finishBody, 'finish must have been observed').not.toBeNull()
  expect(finishBody!.restarting, 'a hand-run server must not claim a self-restart').toBe(false)
  expect(finishBody!.restart_hint).toMatch(/my-crew serve|systemctl|docker|podman/i)
  expect(finishBody!.message).toMatch(/thủ công/i)

  // Setup really is complete: the app now asks for the credentials just created.
  await expect(page.locator('body')).toContainText(/Đăng nhập/i)

  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
})
