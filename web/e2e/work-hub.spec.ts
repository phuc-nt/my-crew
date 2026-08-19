// Phase 5 work hub smoke: the board's previously-hidden fields, the task detail page,
// approving from the shared queue, and the schedule.
//
// Real browser because each fact is cross-cutting in a way unit tests miss: the board
// card's badges depend on optional payload fields, the task page arrives as its own
// lazy chunk keyed by room, and the approvals queue is one component mounted by two
// hubs — approving here has to hit the same endpoint the chat pane would.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { mockOfficeApi } from './support/mock-api'

const LANES = [
  {
    id: 'running',
    cards: [
      {
        task_id: 't-1',
        title: 'Soạn báo cáo tuần',
        pic_id: 'tro-ly-pm',
        room_id: 'room-alpha',
        status: 'running',
        created_at: '2026-08-19T01:00:00Z',
        steps_done: 2,
        steps_total: 4,
        // The two fields the old kanban had but the plan wanted surfaced on the card.
        steps_needs_shell: 1,
        queue_position: 3,
      },
    ],
  },
  {
    id: 'open',
    cards: [
      {
        task_id: 't-2',
        title: 'Rà soát hợp đồng',
        pic_id: 'ke-toan',
        room_id: 'room-beta',
        status: 'open',
        created_at: '2026-08-19T02:00:00Z',
        steps_done: 0,
        steps_total: 2,
      },
    ],
  },
]

test('16. bảng việc hiện hàng đợi, sandbox và lọc theo người phụ trách', async ({ page }) => {
  await mockOfficeApi(page, { boardLanes: LANES })
  await page.goto('/work')

  await expect(page.getByTestId('work-page')).toBeVisible()
  await expect(page.locator('.task-card')).toHaveCount(2)

  // Queue position and sandbox count are the fields this phase set out to expose.
  await expect(page.locator('.task-badge.queued')).toHaveText(/xếp sau 3/)
  await expect(page.locator('.task-badge.sandbox')).toHaveText(/1 sandbox/)

  // Filtering by owner is client-side over the one board payload.
  await page.locator('.board-filters select').selectOption('ke-toan')
  await expect(page.locator('.task-card')).toHaveCount(1)
  await expect(page.locator('.task-card-title')).toHaveText('Rà soát hợp đồng')
})

test('17. thẻ việc mở trang chi tiết theo phòng, có bước và liên kết chéo', async ({ page }) => {
  await mockOfficeApi(page, {
    boardLanes: LANES,
    artifacts: {
      tasks: [
        {
          task_id: 't-1',
          title: 'Soạn báo cáo tuần',
          pic_id: 'tro-ly-pm',
          status: 'running',
          steps: [
            { step_id: 's-1', title: 'Thu thập số liệu', assigned_to: 'tro-ly-pm',
              status: 'done', seq: 1, step_type: 'content' },
            { step_id: 's-2', title: 'Soát lại', assigned_to: 'ke-toan',
              status: 'running', seq: 2, step_type: 'review' },
          ],
        },
      ],
    },
    stepArtifact: {
      task_id: 't-1',
      step_title: 'Thu thập số liệu',
      result_text: 'Doanh thu tháng 8 tăng 12%.',
      attempt: '1',
      self_check_failed: false,
    },
  })
  await page.goto('/work')

  await page.locator('.task-card-link').first().click()
  // Addressed by ROOM id — the artifact index, the office and the chat thread share it.
  await expect(page).toHaveURL(/\/work\/task\/room-alpha$/)
  await expect(page.getByTestId('task-detail-page')).toBeVisible()

  // Step progress comes from the room index, not the card's bare counts.
  await expect(page.locator('.step-row')).toHaveCount(2)
  await expect(page.locator('.step-row.is-done')).toHaveCount(1)
  await expect(page.locator('.step-row.is-running')).toHaveCount(1)

  // Opening a step shows what it produced, via the same renderer the chat drawer uses.
  await page.locator('.step-open').first().click()
  await expect(page.locator('.artifact-text')).toHaveText(/tăng 12%/)

  // The room's other two homes stay one click away.
  await expect(page.getByRole('link', { name: DICT.vi['taskDetail.openChat'] })).toHaveAttribute(
    'href',
    '/chat/room-alpha',
  )
  await expect(page.getByRole('link', { name: DICT.vi['taskDetail.openOffice'] })).toHaveAttribute(
    'href',
    '/office?room=room-alpha',
  )
})

test('18. duyệt từ hàng chờ dùng chung ở trang Việc', async ({ page }) => {
  const approved: string[] = []
  await mockOfficeApi(page, {
    pendingApprovals: [
      {
        id: 7,
        agent_id: 'tro-ly-pm',
        reason: 'Gửi email cho khách hàng',
        status: 'pending',
        created_at: '2026-08-19T03:00:00Z',
        action: { type: 'email_send', to: 'khach@example.com', subject: 'Báo giá' },
      },
    ],
  })
  // Recorded before the mock's own handler so the click's effect is observable.
  await page.route('**/api/agents/*/approvals/*/approve', async (route) => {
    approved.push(new URL(route.request().url()).pathname)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ agent_id: 'tro-ly-pm', pending: [] }),
    })
  })
  await page.goto('/work')

  const card = page.locator('.pending-card').first()
  await expect(card).toContainText('Gửi email cho khách hàng')
  await card.getByRole('button', { name: DICT.vi['pending.approve'] }).click()

  // The work hub reaches the per-agent approve route — the same one the chat pane uses.
  await expect.poll(() => approved).toEqual(['/api/agents/tro-ly-pm/approvals/7/approve'])
})

test('19. tab lịch chạy nằm trong URL và liệt kê lần chạy sắp tới', async ({ page }) => {
  await mockOfficeApi(page, {
    scheduleItems: [
      { agent_id: 'tro-ly-pm', kind: 'daily', next_ts: '2099-01-01T00:00:00Z', label: 'Báo cáo ngày' },
    ],
  })
  await page.goto('/work?tab=schedule')

  // A deep link lands on the tab rather than falling back to the board.
  await expect(page.locator('.agent-tabs button.tab-active')).toHaveText(
    DICT.vi['workHub.tabSchedule'],
  )
  await expect(page.locator('.schedule-row')).toHaveCount(1)
  await expect(page.locator('.schedule-what')).toContainText('Báo cáo ngày')
})
