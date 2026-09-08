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

// The task plan pinned under the thread: rendered from the room's artifact index, with a
// done/total per task, so progress is readable without leaving the conversation.
test('56. dải việc-đang-làm hiện dưới luồng chat với tiến độ từng bước', async ({ page }) => {
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(2, ROOM) },
    artifacts: {
      tasks: [{
        task_id: 't-abc', title: 'Soạn báo cáo tuần cho sếp', pic_id: 'tro-ly-pm', status: 'in_progress',
        steps: [
          { step_id: 's1', title: 'thu thập số liệu', assigned_to: 'ke-toan', status: 'done', seq: 3, step_type: 'research' },
          { step_id: 's2', title: 'viết báo cáo', assigned_to: 'tro-ly-pm', status: 'running', seq: 4, step_type: 'content' },
          { step_id: 's3', title: 'gửi sếp', assigned_to: 'tro-ly-pm', status: 'open', seq: 0, step_type: 'delivery' },
        ],
      }],
    },
  })
  await page.goto(`/chat/${ROOM}`)

  const strip = page.locator('[data-testid="thread-todo-strip"]')
  await expect(strip).toBeVisible()
  await expect(strip.locator('[data-testid="todo-progress"]')).toHaveText('1/3 bước')
  await expect(strip.locator('.todo-step')).toHaveCount(3)
  await expect(strip.locator('.todo-step.is-running')).toContainText('viết báo cáo')
  // The strip sits between the log and the composer — above the input, below the thread.
  const stripBox = await strip.boundingBox()
  const inputBox = await page.getByPlaceholder(DICT.vi['assignComposer.placeholderRoom']).boundingBox()
  expect(stripBox!.y + stripBox!.height).toBeLessThanOrEqual(inputBox!.y + 1)
})

// Typing while the previous message is still in flight parks the text and sends it on
// its own once the reply lands — no lost keystrokes, no double submit.
test('57. gõ tiếp khi đang chờ trả lời: tin xếp hàng rồi tự gửi sau', async ({ page }) => {
  const mock = await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(2, ROOM) },
    roomChat: { intent: 'question', reply: 'Đang ở bước 2.' },
    roomChatDelayMs: 800,
  })
  await page.goto(`/chat/${ROOM}`)
  const box = page.getByPlaceholder(DICT.vi['assignComposer.placeholderRoom'])
  await box.fill('tiến độ sao rồi?')
  await box.press('Enter')
  await box.fill('gửi tôi bản nháp nhé')
  await box.press('Enter')

  const queue = page.locator('[data-testid="composer-queue"], .office-composer-queue')
  await expect(queue).toContainText('gửi tôi bản nháp nhé')
  await expect.poll(() => mock.roomChatWrites.map((w) => w.message)).toEqual([
    'tiến độ sao rồi?',
    'gửi tôi bản nháp nhé',
  ])
  await expect(queue).toHaveCount(0)
})

// A red row carries its own "why + what next" so the CEO is never left with a bare error.
test('58. bước lỗi trong luồng chat kèm ghi chú vì sao và làm gì tiếp', async ({ page }) => {
  const events = makeRoomEvents(2, ROOM)
  events.push({
    seq: 3, ts: '2026-07-31T09:01:00Z', author: 'coordinator', source_room_id: ROOM,
    kind: 'step_status',
    body: { status: 'failed', step_title: 'gửi email khách', task_id: 't-abc', step_id: 's2' },
  })
  await mockOfficeApi(page, { roomEvents: { [ROOM]: events } })
  await page.goto(`/chat/${ROOM}`)

  const guide = page.locator('.chat-thread-log .failure-guide')
  await expect(guide).toHaveCount(1)
  await expect(guide).toContainText(DICT.vi['failureGuide.whyLabel'])
  await expect(guide).toContainText(DICT.vi['failureGuide.step_failed.next'])
})

// Live tool-call telemetry folds behind one "Hoạt động nền" row; a call to the `task`
// delegation tool is counted as a subagent, and expanding lists every line.
test('62. ngăn "Hoạt động nền" gom các dòng đang chạy, đếm nhân sự phụ, mở ra thấy từng dòng', async ({ page }) => {
  const events = makeRoomEvents(2, ROOM)
  events.push(
    {
      seq: 3, ts: '2026-07-31T09:01:00Z', author: 'content', source_room_id: ROOM,
      kind: 'step_activity',
      body: { agent: 'content', task: 't-abc', step: 'viết báo cáo', tool: 'web_search', count: 3, phase: 'calling-tool' },
    },
    {
      seq: 4, ts: '2026-07-31T09:01:05Z', author: 'tro-ly-pm', source_room_id: ROOM,
      kind: 'step_activity',
      body: { agent: 'tro-ly-pm', task: 't-abc', step: 'tổng hợp', tool: 'task', count: 1, phase: 'calling-tool' },
    },
  )
  await mockOfficeApi(page, { roomEvents: { [ROOM]: events } })
  await page.goto(`/chat/${ROOM}`)

  const drawer = page.locator('[data-testid="background-activity"]')
  await expect(drawer).toBeVisible()
  await expect(drawer.locator('[data-testid="background-activity-count"]')).toHaveText('2')
  await expect(drawer.locator('[data-testid="background-activity-subagents"]')).toHaveText(
    DICT.vi['backgroundActivity.subagents'].replace('{n}', '1'),
  )
  // Collapsed: the newest line inline, no list yet.
  await expect(drawer).toContainText('tổng hợp')
  await expect(drawer.locator('.background-activity-item')).toHaveCount(0)

  await drawer.getByRole('button').click()
  const items = drawer.locator('.background-activity-item')
  await expect(items).toHaveCount(2)
  await expect(items.nth(0)).toContainText('web_search')
  await expect(items.nth(1)).toHaveClass(/is-subagent/)
  await expect(items.nth(1)).toContainText(
    DICT.vi['backgroundActivity.subagentLine'].replace('{step}', 'tổng hợp').replace('{count}', '1'),
  )
})

// A step that died mid-answer shows what it had drafted, its sources, why it stopped, and
// one button that dispatches the retry; the card leaves once the step is running again.
test('63. câu trả lời dở: nháp + nguồn + lỗi + nút làm tiếp, thẻ biến mất khi bước chạy lại', async ({ page }) => {
  const stalled = {
    task_id: 't-abc', title: 'Soạn báo cáo tuần cho sếp', pic_id: 'tro-ly-pm', status: 'stalled',
    steps: [
      { step_id: 's1', title: 'thu thập số liệu', assigned_to: 'ke-toan', status: 'done', seq: 3, step_type: 'research' },
      { step_id: 's2', title: 'viết báo cáo', assigned_to: 'tro-ly-pm', status: 'failed', seq: 4, step_type: 'content' },
    ],
  }
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(2, ROOM) },
    artifacts: { tasks: [stalled] },
    stepArtifact: {
      task_id: 't-abc', step_title: 'viết báo cáo', attempt: 'a1', self_check_failed: false,
      status: 'failed', error: 'LLM timeout after 120s',
      result_text: '## Nháp\n- Doanh thu tăng 12% (https://vnexpress.net/kinh-doanh/a)\n- Chi phí theo https://cafef.vn/b',
    },
    artifactsAfterAction: {
      tasks: [{ ...stalled, status: 'in_progress', steps: [stalled.steps[0], { ...stalled.steps[1], status: 'running' }] }],
    },
  })
  await page.goto(`/chat/${ROOM}`)

  const card = page.locator('[data-testid="interrupted-answer"]')
  await expect(card).toHaveCount(1)
  await expect(card).toContainText(DICT.vi['interrupted.label'])
  await expect(card.locator('.interrupted-answer-partial')).toContainText('Doanh thu tăng 12%')
  await expect(card.locator('.citation-chip')).toHaveCount(2)
  await expect(card.locator('.interrupted-answer-error')).toContainText('LLM timeout after 120s')
  await expect(card.locator('.failure-guide')).toContainText(DICT.vi['failureGuide.step_failed.next'])
  // The card sits above the todo strip, which still lists the dead step.
  await expect(page.locator('[data-testid="thread-todo-strip"] .todo-step.is-failed')).toHaveCount(1)

  const retry = page.waitForRequest((r) =>
    r.method() === 'POST' && r.url().endsWith('/api/team-tasks/t-abc/steps/s2/retry'))
  await card.getByRole('button', { name: DICT.vi['interrupted.retry'] }).click()
  await retry
  await expect(card).toHaveCount(0)
  await expect(page.locator('[data-testid="thread-todo-strip"] .todo-step.is-running')).toContainText('viết báo cáo')
})

// A delivered step's text names its sources inline; the drawer turns them into chips.
test('64. chip nguồn tham khảo dưới kết quả bước trong ngăn kết quả', async ({ page }) => {
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(2, ROOM) },
    artifacts: {
      tasks: [{
        task_id: 't-abc', title: 'Soạn báo cáo tuần cho sếp', pic_id: 'tro-ly-pm', status: 'done',
        steps: [
          { step_id: 's1', title: 'thu thập số liệu', assigned_to: 'ke-toan', status: 'done', seq: 3, step_type: 'research' },
        ],
      }],
    },
    stepArtifact: {
      task_id: 't-abc', step_title: 'thu thập số liệu', attempt: 'a1', self_check_failed: false,
      status: 'done', error: '',
      result_text: 'Số liệu lấy từ https://www.gso.gov.vn/du-lieu và https://vnexpress.net/a; đối chiếu https://gso.gov.vn/khac.',
    },
  })
  await page.goto(`/chat/${ROOM}`)
  await page.getByRole('button', { name: DICT.vi['artifacts.open'] }).click()
  await page.locator('.artifact-step').click()
  await expect(page.locator('.artifact-text')).toContainText('Số liệu lấy từ')

  const chips = page.locator('.artifact-detail .citation-chips a')
  await expect(chips).toHaveCount(2)
  await expect(chips.nth(0)).toHaveText('gso.gov.vn')
  await expect(chips.nth(0)).toHaveAttribute('href', 'https://www.gso.gov.vn/du-lieu')
  await expect(chips.nth(1)).toHaveText('vnexpress.net')
  await expect(chips.nth(1)).toHaveAttribute('rel', 'noopener noreferrer')
})
