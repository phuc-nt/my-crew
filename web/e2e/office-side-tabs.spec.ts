// v56 smoke: the v55 right-column behaviors — watch-run grouping ×N, status filter +
// search, and the results-tab ● dot on a LIVE handoff (the bug fixed three times in
// v55; only a real browser + real EventSource exercises the reconnect path).
import { expect, test, type Page } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { makeHandoff, makeRoomEvents, mockOfficeApi } from './support/mock-api'

const ROOM = 'room-bao-cao-tuan'

async function openOffice(page: Page, path = '/office') {
  const mock = await mockOfficeApi(page, { roomEvents: { [ROOM]: makeRoomEvents(44) } })
  await page.goto(path)
  await expect(page.locator('.office-unified')).toBeVisible()
  return mock
}

test('5. 17 watch-run cùng tiêu đề gộp thành 1 dòng ×17, xổ ra được', async ({ page }) => {
  await openOffice(page)
  const groupRow = page.getByRole('button', { name: /×17/ })
  await expect(groupRow).toBeVisible()
  await expect(groupRow).toHaveAttribute('aria-expanded', 'false')
  // Collapsed: the runs are NOT 17 separate rows in the list.
  await expect(page.locator('.workroom-group-runs')).toHaveCount(0)
  await groupRow.click()
  await expect(groupRow).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('.workroom-group-runs button')).toHaveCount(17)
})

test('6. lọc ✓ tắt mặc định; search bỏ qua status filter (hành vi chốt v55)', async ({ page }) => {
  await openOffice(page)
  const blogRoom = page.getByRole('button', { name: /Viết bài blog sản phẩm/ })
  await expect(page.getByRole('button', { name: /Soạn báo cáo tuần/ })).toBeVisible()
  await expect(blogRoom).toHaveCount(0) // status 'xong' → hidden at rest
  await page
    .getByPlaceholder(DICT.vi['workroomList.searchPlaceholder'])
    .fill('blog')
  await expect(blogRoom).toBeVisible() // search reveals it despite the ✓ filter being off
})

test('7. chấm ● tab Kết quả: chỉ khi handoff tới LIVE, tắt khi mở tab', async ({ page }) => {
  const mock = await openOffice(page, `/office?room=${ROOM}`)
  const resultsTab = page.getByRole('button', { name: DICT.vi['officeSide.tabResults'] })
  await expect(resultsTab).toBeVisible()
  // Baseline: the room's replayed history has no handoff yet — no dot.
  await expect(page.locator('.office-side-badge')).toHaveCount(0)
  // A handoff lands live (delivered on the next EventSource reconnect, ~100ms).
  mock.pushRoomEvents(ROOM, [makeHandoff(45)])
  await expect(page.locator('.office-side-badge')).toBeVisible({ timeout: 10_000 })
  // Opening the results tab clears the dot and shows the artifact panel.
  await resultsTab.click()
  await expect(page.locator('.office-side-badge')).toHaveCount(0)
  await expect(page.locator('.office-side-body')).toBeVisible()
  await expect(
    page.getByRole('button', { name: DICT.vi['officeSide.tabRooms'] }),
  ).toBeVisible()
})
