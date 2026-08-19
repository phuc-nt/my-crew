// The office hub as an observation deck. Ported from office-cockpit.spec.ts: the layout
// invariants are the same ones the v55/v56 rounds fought for — the page must fit one
// viewport, the feed must scroll INSIDE its frame, and an overlay must never reflow the
// columns underneath it — but the surfaces they are measured on changed, because giao
// việc moved into the chat hub and its modal shortcut.
//
// Every assertion is still a measurement (rect/scrollHeight/scrollY), never a bare
// visibility check: jsdom cannot do layout, which is exactly how the earlier rounds
// shipped a green suite over a broken screen.
import { expect, test, type Page } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { makeRoomEvents, mockOfficeApi, type OfficeApiMockOptions } from './support/mock-api'

const ROOM = 'room-bao-cao-tuan'

async function openOffice(page: Page, path = '/office', opts?: OfficeApiMockOptions) {
  const mock = await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(44, ROOM) },
    ...opts,
  })
  await page.goto(path)
  await expect(page.locator('[data-testid="office-page"]')).toBeVisible()
  return mock
}

/** Wait until the feed actually overflows its frame (SSE replay has landed). */
async function waitForFeedOverflow(page: Page) {
  await expect
    .poll(async () =>
      page.locator('.office-unified-log').evaluate((el) => el.scrollHeight - el.clientHeight))
    .toBeGreaterThan(0)
}

test('1. page không scroll ở 1440×900 — cả màn là 1 viewport', async ({ page }) => {
  await openOffice(page)
  const m = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
  }))
  expect(m.scrollHeight).toBeLessThanOrEqual(m.clientHeight + 1)
})

test('2. feed scroll TRONG khung — page đứng yên', async ({ page }) => {
  await openOffice(page, `/office?room=${ROOM}`)
  await waitForFeedOverflow(page)
  const r = await page.locator('.office-unified-log').evaluate((el) => {
    el.scrollTop = 99_999
    return { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, scrollTop: el.scrollTop }
  })
  expect(r.scrollHeight).toBeGreaterThan(r.clientHeight)
  expect(r.scrollTop).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
})

test('3. modal giao việc nhanh là overlay — không đẩy cột nào bên dưới', async ({ page }) => {
  await openOffice(page)
  const zones = ['.office-unified-center', '.office-unified-side', '[data-testid="office-floor"]']
  const measure = async () => {
    const rects: Record<string, { x: number; y: number; h: number }> = {}
    for (const sel of zones) {
      const box = await page.locator(sel).boundingBox()
      expect(box, sel).not.toBeNull()
      rects[sel] = { x: box!.x, y: box!.y, h: box!.height }
    }
    return rects
  }
  const before = await measure()
  await page.locator('[data-testid="office-quick-assign"]').click()
  await expect(page.locator('[data-testid="quick-assign-modal"]')).toBeVisible()
  const after = await measure()
  for (const sel of zones) {
    expect(Math.abs(after[sel].x - before[sel].x), `${sel} x`).toBeLessThanOrEqual(1)
    expect(Math.abs(after[sel].y - before[sel].y), `${sel} y`).toBeLessThanOrEqual(1)
    expect(Math.abs(after[sel].h - before[sel].h), `${sel} height`).toBeLessThanOrEqual(1)
  }
  // Escape returns the deck exactly as it was — a dialog that strands the reader is
  // worse than no shortcut at all.
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-testid="quick-assign-modal"]')).toHaveCount(0)
})

test('4. click bàn mở inspector, hiện việc đang chạy của nhân sự đó', async ({ page }) => {
  await openOffice(page)
  // The 2D fallback table is the reliable click target in a headless browser (the
  // Canvas needs a real WebGL pick); it renders the SAME derived desk map.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.reload()
  const row = page.locator('.office-3d-fallback-table tbody tr').first()
  await expect(row).toBeVisible()
  const agentId = (await row.locator('td').first().innerText()).trim()
  await row.click()
  const inspector = page.locator('.desk-inspector')
  await expect(inspector).toBeVisible()
  await expect(inspector).toContainText(agentId)
})

test('9. badge SPRINT hiện trong preview giao việc trước khi xác nhận', async ({ page }) => {
  // The composer moved into the quick-assign modal, but it IS the same component, so the
  // preview round-trip and its routing badge must survive the move.
  await openOffice(page, '/office', {
    assignPreview: {
      preview_text: 'KẾ HOẠCH: 1 bước, @tro-ly-pm làm thẳng',
      task_id: 't-sprint', plan_hash: 'h1', pic_id: 'tro-ly-pm',
      auto_confirmed: false, route_mode: 'sprint',
    },
  })
  await page.locator('[data-testid="office-quick-assign"]').click()
  await page
    .getByPlaceholder(DICT.vi['assignComposer.placeholderNew'])
    .fill('@tro-ly-pm viết nháp thông báo nội bộ')
  await page.getByRole('button', { name: DICT.vi['assignComposer.assign'], exact: true }).click()
  const badge = page.locator('.office-mode-badge-sprint')
  await expect(badge).toBeVisible()
  await expect(badge).toHaveText(DICT.vi['assignComposer.modeSprint'])
})

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('8. mobile stack: page scroll được, sàn 3D đứng trên feed', async ({ page }) => {
    await openOffice(page)
    await page.evaluate(() => window.scrollTo(0, 500))
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
    await page.evaluate(() => window.scrollTo(0, 0))
    const floor = await page.locator('[data-testid="office-floor"]').boundingBox()
    const feed = await page.locator('.office-unified-log').boundingBox()
    expect(floor).not.toBeNull()
    expect(feed).not.toBeNull()
    expect(floor!.y).toBeLessThan(feed!.y)
  })
})
