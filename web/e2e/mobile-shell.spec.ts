// Phone-viewport smoke. The desktop specs run at 1440×900 and cannot see any of this:
// the header collapses into a ⋯ menu, the hub nav becomes a fixed bottom tab bar, and
// the chat hub splits into two screens (list, then thread) the way a chat app does.
//
// The regressions these guard against are all layout facts a jsdom test cannot measure —
// twice during this arc a numerically-green probe hid a real visual break, so every
// assertion here is a measurement against the real 390px viewport.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { mockOfficeApi } from './support/mock-api'

const HUBS = [
  { path: '/chat', key: 'hub.chat' },
  { path: '/office', key: 'hub.office' },
  { path: '/work', key: 'hub.work' },
  { path: '/team', key: 'hub.team' },
  { path: '/system', key: 'hub.system' },
] as const

/**
 * Widest right edge of any element that is NOT inside a horizontal scroller, in CSS px.
 *
 * A scroller is allowed to hold content wider than itself — that is the point of it
 * (the room chips on /office and markdown tables in a chat bubble both rely on this).
 * So both the scroller box and everything under it are excluded, and what remains is
 * content that genuinely pushes the page sideways.
 */
async function widestEdge(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const w = document.documentElement.clientWidth
    const scrollers = new Set<Element>()
    for (const el of document.querySelectorAll('body *')) {
      const overflowX = getComputedStyle(el).overflowX
      if (overflowX === 'auto' || overflowX === 'scroll') scrollers.add(el)
    }
    const inScroller = (el: Element) => {
      for (let node: Element | null = el; node; node = node.parentElement) {
        if (scrollers.has(node)) return true
      }
      return false
    }

    let worst = w
    let culprit = ''
    for (const el of document.querySelectorAll('body *')) {
      if (inScroller(el)) continue
      const right = Math.ceil(el.getBoundingClientRect().right)
      if (right > worst) {
        worst = right
        culprit = `${el.tagName}.${el.className}`
      }
    }
    return { worst, viewport: w, culprit }
  })
}

test('50. mobile: không hub nào tràn ngang ở 390px', async ({ page }) => {
  await mockOfficeApi(page)
  for (const hub of HUBS) {
    await page.goto(hub.path)
    await page.waitForTimeout(400)
    const { worst, viewport, culprit } = await widestEdge(page)
    expect(worst, `${hub.path} tràn ngang vì ${culprit}`).toBeLessThanOrEqual(viewport + 1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(viewport + 1)
  }
})

test('51. mobile: thanh tab dưới đủ 5 hub, không đè nhau, điều hướng được', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/chat')

  const nav = page.locator('.app-nav-primary')
  await expect(nav).toBeVisible()

  // Fixed to the bottom edge, not scrolled away with the content.
  const navBox = (await nav.boundingBox())!
  const height = page.viewportSize()!.height
  expect(navBox.y + navBox.height).toBeGreaterThan(height - 2)

  // Five tabs sharing the width without overlapping. Labels overlapping while the
  // element count stayed correct is exactly what a screenshot caught during this arc.
  const boxes = []
  for (const hub of HUBS) {
    const link = nav.getByRole('link', { name: DICT.vi[hub.key], exact: false })
    await expect(link).toBeVisible()
    boxes.push((await link.boundingBox())!)
  }
  boxes.sort((a, b) => a.x - b.x)
  for (let i = 1; i < boxes.length; i += 1) {
    expect(boxes[i].x, 'tab đè lên nhau').toBeGreaterThanOrEqual(boxes[i - 1].x + boxes[i - 1].width - 1)
  }

  await nav.getByRole('link', { name: DICT.vi['hub.team'], exact: false }).click()
  await expect(page).toHaveURL(/\/team$/)
})

test('52. mobile: bốn nút chrome nằm trong menu ⋯', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/chat')

  // The inline desktop row is what pushed content ~250px down on a phone.
  await expect(page.locator('.app-header-actions')).toBeHidden()

  const trigger = page.locator('.chrome-overflow-btn')
  await expect(trigger).toBeVisible()
  await expect(page.locator('.chrome-overflow-panel')).toHaveCount(0)
  await trigger.click()
  await expect(page.locator('.chrome-overflow-panel')).toBeVisible()

  // Escape closes it — the panel covers the content, so it must be dismissible.
  await page.keyboard.press('Escape')
  await expect(page.locator('.chrome-overflow-panel')).toHaveCount(0)
})

test('53. mobile: chat là hai màn — danh sách rồi hội thoại, Back quay lại', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/chat')

  const list = page.locator('.chat-conversations')
  await expect(list).toBeVisible()
  await expect(page.locator('.chat-main')).toBeHidden()

  await list.locator('.chat-conversation').first().click()
  await expect(page).toHaveURL(/\/chat\/.+/)
  await expect(list).toBeHidden()
  await expect(page.locator('.chat-main')).toBeVisible()

  // The composer is the point of the screen: it must be inside the viewport, above
  // the fixed tab bar, without the reader scrolling for it. Which composer renders
  // depends on the room — the pinned assistant row uses `.ops-composer`, a workroom
  // uses the shared `.office-composer` — so accept either.
  const composer = page.locator('.office-composer, .ops-composer')
  await expect(composer).toBeVisible()
  const box = (await composer.boundingBox())!
  const navBox = (await page.locator('.app-nav-primary').boundingBox())!
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.y + box.height).toBeLessThanOrEqual(navBox.y + 1)

  await page.locator('.chat-back').click()
  await expect(page).toHaveURL(/\/chat$/)
  await expect(list).toBeVisible()
  await expect(page.locator('.chat-main')).toBeHidden()
})

test('54. mobile: deep link mở thẳng hội thoại', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/chat')
  await page.locator('.chat-conversation').first().click()
  const deepLink = new URL(page.url()).pathname

  // Cold load of the same URL: the thread must mount directly, not the list.
  await page.goto(deepLink)
  await expect(page.locator('.chat-main')).toBeVisible()
  await expect(page.locator('.chat-conversations')).toBeHidden()
})
