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

// v88 P3: one-click unstick — a stalled card on the board offers Retry/Accept/Drop
// straight from the lane, with a real POST to the same task-actions route the task
// detail page uses. No chat detour: this is the "≤2 clicks" contract the phase set.
const STALLED_LANES = [
  {
    id: 'khac',
    cards: [
      {
        task_id: 't-3',
        title: 'Tổng hợp số liệu quý',
        pic_id: 'ke-toan',
        room_id: 'room-gamma',
        status: 'stalled',
        created_at: '2026-08-19T03:00:00Z',
        steps_done: 1,
        steps_total: 2,
        stalled_step: 'thu thập số liệu',
      },
    ],
  },
]

test('20. thẻ việc kẹt hiện lý do và bấm gỡ kẹt đi thẳng đến route hành động', async ({ page }) => {
  const calls: string[] = []
  await mockOfficeApi(page, { boardLanes: STALLED_LANES })
  await page.route('**/api/team-tasks/*/steps/*/retry', async (route) => {
    calls.push(new URL(route.request().url()).pathname)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 't-3', title: 'Tổng hợp số liệu quý', status: 'open', pic_id: 'ke-toan',
        room_id: 'room-gamma', steps: [],
      }),
    })
  })
  await page.goto('/work')

  const card = page.locator('.task-card').first()
  await expect(card).toContainText('thu thập số liệu')
  await card.getByRole('button', { name: DICT.vi['stalledActions.retry'] }).click()

  await expect.poll(() => calls).toEqual(['/api/team-tasks/t-3/steps/_/retry'])
})

test('21. hủy việc trên thẻ yêu cầu xác nhận trước khi gọi route hủy', async ({ page }) => {
  const calls: string[] = []
  await mockOfficeApi(page, { boardLanes: STALLED_LANES })
  await page.route('**/api/team-tasks/*/cancel', async (route) => {
    calls.push(new URL(route.request().url()).pathname)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 't-3', title: 'Tổng hợp số liệu quý', status: 'cancelled', pic_id: 'ke-toan',
        room_id: 'room-gamma', steps: [],
      }),
    })
  })
  await page.goto('/work')

  const card = page.locator('.task-card').first()
  await card.getByRole('button', { name: DICT.vi['stalledActions.cancel'] }).click()
  // Destructive — the first click only opens the confirm dialog, no request yet.
  expect(calls).toEqual([])

  await page.locator('.confirm-dialog').getByRole('button', { name: DICT.vi['stalledActions.cancel'] }).click()
  await expect.poll(() => calls).toEqual(['/api/team-tasks/t-3/cancel'])
})

// v91: the same unstick cluster on the TASK DETAIL page. Board-card coverage above is
// not a substitute: the detail page renders from the room-artifacts query, a different
// cache entry than the board's, so its repaint depends on the mutation invalidating
// `artifacts.room(roomId)` — the exact wiring a review found missing (the panel stayed
// frozen until a remount). These tests fail if that invalidation regresses.
const STALLED_ROOM_ARTIFACTS = {
  tasks: [
    {
      task_id: 't-3',
      title: 'Tổng hợp số liệu quý',
      pic_id: 'ke-toan',
      status: 'stalled',
      steps: [
        { step_id: 's-1', title: 'thu thập số liệu', assigned_to: 'ke-toan',
          status: 'failed', seq: 1, step_type: 'content' },
      ],
    },
  ],
}

/** The same room after the action landed — the task is unstuck, so the panel's reason
 *  line and its recovery buttons must both disappear on re-fetch. */
const UNSTUCK_ROOM_ARTIFACTS = {
  tasks: [
    {
      task_id: 't-3',
      title: 'Tổng hợp số liệu quý',
      pic_id: 'ke-toan',
      status: 'open',
      steps: [
        { step_id: 's-1', title: 'thu thập số liệu', assigned_to: 'ke-toan',
          status: 'pending', seq: 1, step_type: 'content' },
      ],
    },
  ],
}

test('22. gỡ kẹt từ trang chi tiết repaint tại chỗ, không cần tải lại trang', async ({ page }) => {
  await mockOfficeApi(page, {
    artifacts: STALLED_ROOM_ARTIFACTS,
    artifactsAfterAction: UNSTUCK_ROOM_ARTIFACTS,
  })
  // Counts artifact fetches without intercepting them — a spec-level route would shadow
  // the mock's own handler and stop it advancing to the post-action phase.
  let artifactFetches = 0
  page.on('request', (req) => {
    if (/\/api\/office\/rooms\/[^/]+\/artifacts$/.test(new URL(req.url()).pathname))
      artifactFetches += 1
  })
  await page.goto('/work/task/room-gamma')
  await expect(page.getByTestId('task-detail-page')).toBeVisible()
  const fetchesBeforeAction = artifactFetches

  const panel = page.locator('.task-detail-stalled-panel')
  await expect(page.locator('.task-detail-stalled-reason')).toContainText('thu thập số liệu')

  await panel.getByRole('button', { name: DICT.vi['stalledActions.retry'] }).click()

  // The reason line and the recovery trio go away because the room's artifacts were
  // invalidated and re-fetched — the task now reads 'open'.
  await expect(page.locator('.task-detail-stalled-reason')).toHaveCount(0)
  await expect(
    panel.getByRole('button', { name: DICT.vi['stalledActions.retry'] }),
  ).toHaveCount(0)
  // Cancel stays: it is valid on any live task, and the task is merely open now.
  await expect(panel.getByRole('button', { name: DICT.vi['stalledActions.cancel'] })).toBeVisible()

  // Positive proof the repaint came from a RE-FETCH: the room's artifacts were requested
  // again after the action. A window sentinel cannot show this — it survives a client-side
  // remount untouched, so it would only rule out a full document navigation.
  expect(artifactFetches).toBeGreaterThan(fetchesBeforeAction)
})

test('23. hủy việc từ trang chi tiết cần xác nhận rồi repaint trạng thái mới', async ({ page }) => {
  const calls: string[] = []
  await mockOfficeApi(page, {
    artifacts: STALLED_ROOM_ARTIFACTS,
    artifactsAfterAction: {
      tasks: [{ ...UNSTUCK_ROOM_ARTIFACTS.tasks[0], status: 'cancelled', steps: [] }],
    },
  })
  // A listener, not a route: intercepting here would shadow the mock's own cancel
  // handler (last route registered wins), and that handler is what advances the
  // room artifacts to their post-action phase.
  page.on('request', (req) => {
    const { pathname } = new URL(req.url())
    if (req.method() === 'POST' && pathname.endsWith('/cancel')) calls.push(pathname)
  })
  await page.goto('/work/task/room-gamma')

  const panel = page.locator('.task-detail-stalled-panel')
  await panel.getByRole('button', { name: DICT.vi['stalledActions.cancel'] }).click()
  expect(calls).toEqual([]) // destructive: the first click only opens the dialog

  await page
    .locator('.confirm-dialog')
    .getByRole('button', { name: DICT.vi['stalledActions.cancel'] })
    .click()
  await expect.poll(() => calls).toEqual(['/api/team-tasks/t-3/cancel'])

  // A cancelled task is terminal — the whole action panel leaves the page.
  await expect(page.locator('.task-detail-stalled-panel')).toHaveCount(0)
})

test('24. giao lại seed brief sang composer đúng một lần', async ({ page }) => {
  await mockOfficeApi(page, { artifacts: STALLED_ROOM_ARTIFACTS })
  await page.goto('/work/task/room-gamma')

  await page.getByRole('button', { name: DICT.vi['taskDetail.reassign'] }).click()

  // Lands on the overview composer with the old brief + PIC mention already filled.
  await expect(page).toHaveURL(/\/chat$/)
  const composer = page.locator('.office-composer input[type="text"]')
  await expect(composer).toHaveValue('@ke-toan Tổng hợp số liệu quý')

  // One-shot: arriving replaces its own history entry with a state-less one, so a
  // reload of that entry re-mounts the composer with no seed. Reload (not in-app
  // navigation) is the honest probe here — the browser restores typed input across
  // in-app history moves regardless of what the app does with router state.
  await page.reload()
  await expect(page).toHaveURL(/\/chat$/)
  await expect(page.locator('.office-composer input[type="text"]')).toHaveValue('')
})
