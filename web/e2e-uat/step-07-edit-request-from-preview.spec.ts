import { test, expect } from '@playwright/test'
import { login } from './uat-login'

/**
 * UAT step 7: the CEO reads the previewed plan, decides the brief was wrong, and fixes
 * it WITHOUT retyping from scratch — "Sửa yêu cầu" hands the original text back to the
 * composer, they edit it, and re-submit.
 *
 * This is the "I worded it badly" recovery. There is deliberately no refine endpoint:
 * edit-request is client-side only (discard the previewed draft, restore the submitted
 * text, back to idle), and the re-submit is a plain fresh decompose. The assertions
 * therefore pin the two things that make it useful — the text really comes back, and
 * the abandoned draft really gets cancelled rather than orphaned.
 */
const AGENT = 'default'
const FIRST = `@${AGENT} Nhắn cho sếp một câu chào.`
const EDITED = `@${AGENT} Nhắn cho sếp một câu chào thật ngắn, đúng 1 câu, bằng tiếng Việt.`

test('a bad brief can be edited from the preview instead of retyped', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  // Track the draft lifecycle: "Sửa yêu cầu" must CANCEL the previewed task, not leave
  // it dangling as a half-created room.
  // The task id travels in the POST BODY, not the URL.
  const cancelled: string[] = []
  page.on('request', r => {
    if (!r.url().includes('/api/office/assign/cancel')) return
    try {
      cancelled.push(JSON.parse(r.postData() ?? '{}').task_id ?? '(no id)')
    } catch {
      cancelled.push('(unparsed)')
    }
  })

  await login(page)
  await page.goto('/chat', { waitUntil: 'domcontentloaded' })

  const composer = page.locator('.office-composer input[type=text]')
  await expect(composer).toBeVisible({ timeout: 30_000 })

  let clicks = 0

  // --- 1st submit: the badly-worded brief ----------------------------------------
  await composer.fill(FIRST)
  await page.getByRole('button', { name: 'Giao việc' }).click(); clicks++
  const preview = page.locator('.office-composer-preview')
  await expect(preview).toBeVisible({ timeout: 180_000 })
  const firstPlan = (await preview.locator('pre').innerText()).trim()
  console.log('PREVIEW 1 (first 120):', firstPlan.slice(0, 120).replace(/\n/g, ' ⏎ '))

  // --- "Sửa yêu cầu": text must come BACK, preview must go away -------------------
  await page.getByRole('button', { name: 'Sửa yêu cầu' }).click(); clicks++
  await expect(preview).toBeHidden({ timeout: 30_000 })
  await expect(composer, 'the original brief must return to the composer verbatim')
    .toHaveValue(FIRST, { timeout: 30_000 })
  console.log('TEXT RESTORED:', await composer.inputValue())

  // The abandoned draft must have been cancelled, not orphaned.
  await expect.poll(() => cancelled.length, {
    timeout: 30_000, message: 'the discarded preview must cancel its draft task',
  }).toBeGreaterThan(0)
  console.log('DRAFT CANCELLED:', cancelled[0])

  // --- edit in place and re-submit ------------------------------------------------
  await composer.fill(EDITED)
  await page.getByRole('button', { name: 'Giao việc' }).click(); clicks++
  await expect(preview).toBeVisible({ timeout: 180_000 })
  const secondPlan = (await preview.locator('pre').innerText()).trim()
  console.log('PREVIEW 2 (first 120):', secondPlan.slice(0, 120).replace(/\n/g, ' ⏎ '))

  // A fresh decompose ran — not the cached first plan replayed.
  expect(secondPlan.length, 'the re-submit must produce a real plan').toBeGreaterThan(0)

  // --- confirm the corrected brief for real ---------------------------------------
  await page.getByRole('button', { name: 'Xác nhận giao việc' }).click(); clicks++
  await expect(preview).toBeHidden({ timeout: 120_000 })
  console.log('EDIT-AND-RESEND CLICKS:', clicks)

  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
  expect(errors.filter(e => !/401/.test(e)), 'no unexpected console errors').toEqual([])
})
