// The office side column's room list: watch-run grouping ×N and the status filter +
// search interplay. Both are DOM-count measurements over a 44-event replay, so only a
// real browser exercises them. (The results-tab ● dot that used to live here went away
// with the side tabs — deliveries now surface in the chat hub's own thread.)
import { expect, test, type Page } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { makeRoomEvents, mockOfficeApi } from './support/mock-api'

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
