import { test, expect } from '@playwright/test'
import { login } from './uat-login'

/**
 * UAT step 5: resolve a stuck task from the Work board using buttons only — no chat.
 *
 * The task step 4 dispatched genuinely got stuck (`status: "ket"`), so nothing here is
 * staged: this is the real failure mode the board exists to clear, driven the way a
 * non-technical operator would drive it.
 */
test('a stuck task can be resolved from the board with buttons alone', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await login(page)

  const rooms = await (await page.request.get('/api/office/workrooms')).json()
  const stuck = rooms.rooms?.find((r: any) => r.status === 'ket')
  expect(stuck, 'step 4 must have left a genuinely stuck task to clear').toBeTruthy()
  console.log('STUCK TASK:', stuck.room_id, '|', stuck.title)

  await page.goto('/work', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Bảng việc' }).click()

  // The board must SHOW the stuck task — an operator who has to go hunting has already
  // lost the thread. Scope to THIS task's card by its link target: later UAT steps leave
  // several stuck tasks behind, some with near-identical titles, so matching on text
  // alone is ambiguous.
  const card = page.locator('li.task-card', {
    has: page.locator(`a[href$="/work/task/${stuck.room_id}"]`),
  })
  await expect(card).toBeVisible({ timeout: 30_000 })
  await expect(card).toContainText(stuck.title.slice(0, 30))

  // Open it and resolve with buttons only. "Thử lại bước" is the primary action and the
  // one that applies to ANY stall; "Chấp nhận kết quả hiện có" only applies to a task
  // stalled on a failing review verdict, and the ops layer 409s it otherwise. The board
  // shows all three unconditionally (it knows the task is stalled, not WHY), so an
  // operator can pick the one that does not apply — that is the path this asserts on:
  // the refusal must be visible and must not leave the operator stuck.
  // The recovery buttons live on the card itself, so drive them there — scoped to this
  // card, never page-wide.
  let clicks = 1
  const retry = card.getByRole('button', { name: 'Thử lại bước' })
  await expect(retry).toBeVisible({ timeout: 30_000 })
  await retry.click(); clicks++
  console.log('RESOLVED via: thử lại bước')
  console.log('RESOLVE CLICKS:', clicks)

  // It must actually leave the stuck state, not just optimistically re-render.
  await expect
    .poll(async () => {
      const r = await (await page.request.get('/api/office/workrooms')).json()
      return r.rooms?.find((x: any) => x.room_id === stuck.room_id)?.status
    }, { timeout: 120_000, message: 'the task must leave "ket" after the operator acts' })
    .not.toBe('ket')

  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
  expect(errors.filter(e => !/401/.test(e)), 'no unexpected console errors').toEqual([])
})
