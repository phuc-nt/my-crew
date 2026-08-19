// Máy vừa cài xong, mở trình duyệt lần đầu. Backend THẬT từ wheel, không mock gì.
//
// Cái này bắt được thứ pytest không bao giờ thấy: bundle FE rơi khỏi wheel, đường dẫn
// asset sai sau khi cài, hoặc trang trắng vì lỗi JS chỉ xảy ra trên bản build. Gate 0.12.0
// bắt đúng loại lỗi này bằng tay.
import { expect, test } from '@playwright/test'

test('cài xong mở lên là ra màn hình sạch, không lỗi console', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(String(e)))

  const res = await page.goto('/')
  expect(res?.status()).toBe(200)

  // Bundle chạy được nghĩa là React đã vẽ ra cái gì đó trong #root; trang trắng thì rỗng.
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 15_000 })
  await page.waitForLoadState('networkidle')

  expect(errors, `lỗi console trên bản cài sạch: ${errors.join(' | ')}`).toEqual([])
})

test('API vẫn trả lời được trên home trống', async ({ request }) => {
  // Home trống đã tự seed ở bước trước — /api/agents phải trả 200 (chưa bật đăng nhập)
  // hoặc 401 (đã bật). Cả hai đều đúng; 500 mới là hỏng, và đó chính là thứ cần chặn.
  const res = await request.get('/api/agents')
  expect([200, 401]).toContain(res.status())
})
