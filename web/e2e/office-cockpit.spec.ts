// v56 smoke: the v55 cockpit layout, measured on real DOM numbers (jsdom cannot do
// layout — "suite xanh ≠ chạy được" happened two rounds in a row). Every assertion is
// a measurement (scrollHeight/rect/scrollY), not a bare visibility check.
//
// Side-column behaviors (grouping/filter/tabs/dot) live in office-side-tabs.spec.ts.
import { expect, test, type Page } from '@playwright/test'
import { makeRoomEvents, mockOfficeApi, type OfficeApiMockOptions } from './support/mock-api'

const ROOM = 'room-bao-cao-tuan'

async function openOffice(page: Page, path = '/office', opts?: OfficeApiMockOptions) {
  const mock = await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(44) },
    ...opts,
  })
  await page.goto(path)
  await expect(page.locator('.office-unified')).toBeVisible()
  await expect(page.locator('.office-composer-bar')).toBeVisible()
  return mock
}

/** Wait until the room feed actually overflows its frame (SSE replay has landed). */
async function waitForFeedOverflow(page: Page) {
  await expect
    .poll(async () =>
      page
        .locator('.office-unified-log')
        .evaluate((el) => el.scrollHeight - el.clientHeight),
    )
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

test('2. feed scroll TRONG khung — page đứng yên (bug 1 v55)', async ({ page }) => {
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

test('3. composer luôn trong viewport — kể cả sau khi scroll feed', async ({ page }) => {
  await openOffice(page, `/office?room=${ROOM}`)
  const inViewport = async () => {
    const box = await page.locator('.office-composer-bar').boundingBox()
    const vh = page.viewportSize()!.height
    expect(box).not.toBeNull()
    expect(box!.y).toBeGreaterThanOrEqual(0)
    expect(box!.y + box!.height).toBeLessThanOrEqual(vh + 1)
    return box!
  }
  const before = await inViewport()
  await waitForFeedOverflow(page)
  await page.locator('.office-unified-log').evaluate((el) => { el.scrollTop = el.scrollHeight })
  const after = await inViewport()
  expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(1)
})

test('4. mở dropdown @mention không đẩy 3 cột (overlay, không phải flow)', async ({ page }) => {
  await openOffice(page)
  const zones = ['.office-rail', '.office-unified-center', '.office-unified-side', '.office-unified-main']
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
  await page.locator('.office-composer-bar input[type="text"]').click()
  await page.locator('.office-composer-bar input[type="text"]').fill('@')
  await expect(page.locator('.office-composer-mentions')).toBeVisible()
  const after = await measure()
  for (const sel of zones) {
    expect(Math.abs(after[sel].x - before[sel].x), `${sel} x`).toBeLessThanOrEqual(1)
    expect(Math.abs(after[sel].y - before[sel].y), `${sel} y`).toBeLessThanOrEqual(1)
    expect(Math.abs(after[sel].h - before[sel].h), `${sel} height`).toBeLessThanOrEqual(1)
  }
})

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('8. mobile stack: page scroll được, composer đứng trên rail', async ({ page }) => {
    await openOffice(page)
    // Document flow is BACK on mobile — the page itself must scroll.
    await page.evaluate(() => window.scrollTo(0, 500))
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
    await page.evaluate(() => window.scrollTo(0, 0))
    const composer = await page.locator('.office-composer-bar').boundingBox()
    const rail = await page.locator('.office-rail').boundingBox()
    expect(composer).not.toBeNull()
    expect(rail).not.toBeNull()
    expect(composer!.y).toBeLessThan(rail!.y)
  })
})
