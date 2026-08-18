// Chat hub smoke: the three-column cockpit, the pending column, the assistant pane and
// the Cmd+K palette. Real browser because every assertion here is a layout measurement,
// a keyboard chord or a lazy-chunk load — none of which jsdom can see.
//
// The pending column is the reason this file matters most: both live queues on the real
// fleet are empty, so its populated state has never been observable outside these mocks.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { makeRoomEvents, mockOfficeApi } from './support/mock-api'

const ROOM = 'room-bao-cao-tuan'

/** Shapes copied from the live endpoints (/api/approvals/pending, /api/clarify/pending). */
const APPROVAL = {
  id: 7,
  agent_id: 'researcher',
  reason: 'Gửi email ra ngoài công ty',
  status: 'pending',
  created_at: '2026-08-19T02:00:00Z',
  action: { type: 'email_send', to: 'khach@example.com', subject: 'Báo giá tháng 8' },
}
const QUESTION = {
  id: 3,
  agent_id: 'content',
  task_id: 't-abc',
  question: 'Bài đăng nên dài bao nhiêu chữ?',
  options: ['300', '800'],
  asked_at: '2026-08-19T01:00:00Z',
  expires_at: '2026-08-20T01:00:00Z',
}

test('11. hub chat có ba cột và cột chờ nằm bên phải luồng hội thoại', async ({ page }) => {
  await mockOfficeApi(page, { roomEvents: { [ROOM]: makeRoomEvents(4, ROOM) } })
  await page.goto(`/chat/${ROOM}`)

  const list = page.locator('.chat-conversations')
  const thread = page.locator('.chat-thread')
  const pending = page.locator('.chat-pending')
  await expect(thread).toBeVisible()

  const [l, t, p] = await Promise.all([
    list.boundingBox(), thread.boundingBox(), pending.boundingBox(),
  ])
  // Left to right, no overlap: the reading order the layout promises.
  expect(l!.x + l!.width).toBeLessThanOrEqual(t!.x + 1)
  expect(t!.x + t!.width).toBeLessThanOrEqual(p!.x + 1)
})

test('12. cột chờ gộp duyệt và câu hỏi, việc chờ lâu nhất lên đầu', async ({ page }) => {
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(4, ROOM) },
    pendingApprovals: [APPROVAL],
    clarifyQuestions: [QUESTION],
  })
  await page.goto(`/chat/${ROOM}`)

  const cards = page.locator('.chat-pending .pending-card')
  await expect(cards).toHaveCount(2)
  // The question was asked an hour earlier, so it is what the CEO should do first.
  await expect(cards.first()).toContainText(QUESTION.question)
  await expect(cards.nth(1)).toContainText(APPROVAL.reason)
})

test('13. luồng chat neo đáy: tin mới nhất sát ô soạn, không trôi lên đỉnh cột', async ({ page }) => {
  // Two events only. Bottom-anchoring is invisible to a full log, so a short room is the
  // case that proves it — this is the defect the cockpit rule was written against.
  await mockOfficeApi(page, { roomEvents: { [ROOM]: makeRoomEvents(2, ROOM) } })
  await page.goto(`/chat/${ROOM}`)

  const log = page.locator('.chat-thread-log')
  await expect(log.locator('> li')).toHaveCount(2)
  // Measured in one evaluate rather than through two boundingBox() round-trips: the log
  // re-renders on each replayed SSE frame, and a locator resolved between the calls can
  // detach before its box is read.
  const slack = await log.evaluate((el) => {
    const rows = el.children
    const last = rows[rows.length - 1].getBoundingClientRect()
    return el.getBoundingClientRect().bottom - last.bottom
  })
  // Flush with the bottom of the column (a few px of padding, not hundreds of slack).
  expect(slack).toBeLessThan(24)
})

test('14. trợ lý báo đang xử lý trong lúc chờ, rồi hiện câu trả lời', async ({ page }) => {
  await mockOfficeApi(page, {
    opsCommands: [{ id: 'get_status', description: 'Xem trạng thái cả đội', readonly: true }],
    opsReply: 'Đội hiện có 11 agent',
    opsReplyDelayMs: 1200,
  })
  await page.goto('/chat/__assistant__')

  const input = page.getByPlaceholder(DICT.vi['chat.inputPlaceholder'])
  await input.fill('đội mình thế nào')
  await page.getByRole('button', { name: DICT.vi['chat.send'], exact: true }).click()

  // The whole point: the CEO sees the request is alive, not a dropped send.
  await expect(page.locator('.ops-thinking')).toHaveText(DICT.vi['chat.thinking'])
  await expect(page.locator('.ops-turn.is-agent')).toContainText('Đội hiện có 11 agent')
  await expect(page.locator('.ops-thinking')).toHaveCount(0)
})

test('15. Cmd+K mở bảng lệnh, gõ ra lịch sử, chọn lệnh thì mồi ô soạn trợ lý', async ({ page }) => {
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(4, ROOM) },
    opsCommands: [{ id: 'get_status', description: 'Xem trạng thái cả đội', readonly: true }],
    searchHits: [{
      // The server wraps matches in »…«; the palette must not render them literally.
      excerpt: 'Tổng hợp và »báo« »cáo« kết quả',
      source: 'step',
      ref: `${ROOM}:52`,
      agent_id: 'researcher',
      ts: '2026-07-11T01:50:17Z',
    }],
  })
  await page.goto(`/chat/${ROOM}`)
  await expect(page.locator('.chat-thread')).toBeVisible()

  // Nothing of the palette is in the entry bundle — it arrives on the chord.
  await expect(page.locator('.palette')).toHaveCount(0)
  await page.keyboard.press('Meta+k')
  const palette = page.getByRole('dialog', { name: DICT.vi['palette.title'] })
  await expect(palette).toBeVisible()
  // All five hubs, before any typing: the palette is a full map of the app.
  await expect(page.locator('.palette-item.is-nav')).toHaveCount(5)

  await page.locator('.palette-input').fill('báo cáo')
  const hit = page.locator('.palette-item.is-history').first()
  await expect(hit).toBeVisible()
  await expect(hit).toContainText('Tổng hợp và báo cáo kết quả')
  await expect(hit).not.toContainText('»')

  await page.locator('.palette-input').fill('trạng thái')
  await page.locator('.palette-item.is-command').first().click()
  // Seeded, not sent: an ops command usually needs finishing before it is a request.
  await expect(page.getByPlaceholder(DICT.vi['chat.inputPlaceholder']))
    .toHaveValue('Xem trạng thái cả đội')
  await expect(page.locator('.ops-turn')).toHaveCount(0)
})
