// Phase 4 team hub smoke: the roster, the inline hire panel, and the eight-tab agent page
// that replaced seven separate top-level routes.
//
// Real browser because all three facts are routing/lazy-loading behaviour the unit tests
// cannot see: the hire panel and the detail page each arrive as their own chunk, and the
// tab state lives in the URL rather than component state.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { agentsFixture } from './fixtures/office-fixtures'
import { expectNoUnmockedRoutes, mockOfficeApi } from './support/mock-api'

const TAB_KEYS = [
  'agentDetail.tabProfile',
  'agentDetail.tabActivity',
  'agentDetail.tabKnowledge',
  'agentDetail.tabSkills',
  'agentDetail.tabChannels',
  'agentDetail.tabBudget',
  'agentDetail.tabMemory',
  'agentDetail.tabAdvanced',
] as const

test('13. hub Đội ngũ liệt kê roster và mỗi dòng link sang trang chi tiết', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/team')

  await expect(page.getByTestId('team-page')).toBeVisible()
  for (const agent of agentsFixture) {
    await expect(page.getByRole('link', { name: agent.id, exact: true })).toHaveAttribute(
      'href',
      `/team/${agent.id}`,
    )
  }
  // Creating is an inline panel, not a route — the gallery is absent until it is opened.
  await expect(page.locator('.staff-template-grid')).toHaveCount(0)
})

test('14. bảng tuyển nạp chunk riêng và hiện mẫu nhân sự kèm chip lịch chạy', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/team')

  await page.getByRole('button', { name: DICT.vi['team.hireOpen'] }).click()
  // The panel is lazy: this only resolves once its chunk has actually been fetched.
  await expect(page.locator('.staff-template-grid')).toBeVisible()
  const grid = page.locator('.staff-template-grid')
  // Scoped to the grid: the roster below also has a "Kiểm định viên" row.
  await expect(grid.getByText('Kiểm định', { exact: true })).toBeVisible()
  // The schedule chip is the one piece the old picker never showed.
  await expect(grid.getByText(/chạy tự động/)).toBeVisible()
})

test('15. trang chi tiết agent gom 8 tab, tab nằm trong URL', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/team/tro-ly-pm')

  await expect(page.getByTestId('agent-detail-page')).toBeVisible()
  const tabs = page.locator('.agent-tabs button')
  await expect(tabs).toHaveCount(TAB_KEYS.length)
  for (const key of TAB_KEYS) {
    await expect(tabs.filter({ hasText: DICT.vi[key] })).toHaveCount(1)
  }

  // Switching a tab rewrites the query string, so one agent's cost view is linkable.
  await tabs.filter({ hasText: DICT.vi['agentDetail.tabBudget'] }).click()
  await expect(page).toHaveURL(/\?tab=budget$/)

  // And a deep link opens straight onto that tab instead of falling back to the first one.
  await page.goto('/team/tro-ly-pm?tab=memory')
  await expect(
    page.locator('.agent-tabs button.tab-active'),
  ).toHaveText(DICT.vi['agentDetail.tabMemory'])
})

// v91 P4: the agent-config form. Component tests already cover each field in isolation;
// what only a browser proves is that a save round-trips through the real query cache —
// the PATCH lands, the settings query re-fetches, and the row repaints with the written
// value instead of the stale one it was mounted with.
test('25. sửa model rồi lịch chạy trên tab Hồ sơ, mỗi field 3 click và repaint giá trị mới', async ({
  page,
}) => {
  const mock = await mockOfficeApi(page, {
    agentProfileSettings: {
      name: 'Trợ lý PM',
      model: 'openai/gpt-4o',
      model_chain: [],
      schedule: { weekly_report: '0 9 * * 1' },
    },
  })
  await page.goto('/team/tro-ly-pm')

  const modelRow = page.locator('dd').filter({ hasText: 'openai/gpt-4o' }).first()
  // Click 1 of 3 — open the row for editing. (Landing on the agent page already shows
  // the Profile tab, so picking the field costs no extra click.)
  await modelRow.getByRole('button', { name: DICT.vi['agentDetail.editBtn'] }).click()
  // Click 2 is the typing itself, click 3 commits.
  await page.locator('.inline-edit-row-form input').fill('anthropic/claude-sonnet-4')
  await page.getByRole('button', { name: DICT.vi['agentDetail.saveBtn'] }).click()

  await expect.poll(() => mock.agentWrites).toEqual([
    { route: 'profile-settings', agentId: 'tro-ly-pm', body: { model: 'anthropic/claude-sonnet-4' } },
  ])
  // Back in read mode showing the NEW value — i.e. re-fetched, not the mount-time value.
  await expect(page.locator('.inline-edit-row-form')).toHaveCount(0)
  await expect(page.getByText('anthropic/claude-sonnet-4')).toBeVisible()

  // Schedule is the multi-line "kind = cron" map; the PATCH replaces the whole block.
  const scheduleRow = page.locator('dd').filter({ hasText: 'weekly_report: 0 9 * * 1' }).first()
  await scheduleRow.getByRole('button', { name: DICT.vi['agentDetail.editBtn'] }).click()
  await page.locator('.inline-edit-row-form textarea').fill('weekly_report = 0 7 * * 2')
  await page.getByRole('button', { name: DICT.vi['agentDetail.saveBtn'] }).click()

  await expect.poll(() => mock.agentWrites.at(-1)).toEqual({
    route: 'profile-settings',
    agentId: 'tro-ly-pm',
    body: { schedule: { weekly_report: '0 7 * * 2' } },
  })
  await expect(page.getByText('weekly_report: 0 7 * * 2')).toBeVisible()
})

test('26. đổi mức tin cậy và bật diễn tập ghi đúng payload rồi đổi nhãn nguồn', async ({ page }) => {
  const mock = await mockOfficeApi(page, {
    agentBand: 'normal',
    agentSafety: { dry_run: false, dry_run_source: 'fleet' },
  })
  await page.goto('/team/tro-ly-pm')

  // The band select commits on change — no separate Save, because picking a value in a
  // dropdown is already the deliberate action.
  const band = page.locator('.agent-band-control select')
  await expect(band).toHaveValue('normal')
  await band.selectOption('trusted')
  await expect.poll(() => mock.agentWrites).toEqual([
    { route: 'band', agentId: 'tro-ly-pm', body: { band: 'trusted' } },
  ])
  await expect(band).toHaveValue('trusted')

  // Dry-run is a per-agent override, so turning it on also flips the source label off
  // "fleet" — the pair is what tells the CEO the setting is now this agent's own.
  // A plain click, not .check(): the box is controlled by server state, so it only
  // flips once the PATCH resolves and the safety query re-fetches — .check() asserts a
  // synchronous state change and would fail on that latency alone.
  await page.locator('.agent-dry-run-toggle input[type="checkbox"]').click()
  await expect.poll(() => mock.agentWrites.at(-1)).toEqual({
    route: 'safety',
    agentId: 'tro-ly-pm',
    body: { dry_run: true },
  })
  await expect(page.locator('.agent-dry-run-toggle')).toContainText(DICT.vi['agentDetail.dryRunOn'])
  await expect(page.locator('.agent-dry-run-source')).toContainText(
    DICT.vi['agentDetail.dryRunSourceProfile'],
  )

  // The agent page is where the fixture gap lived; assert it now serves everything.
  await expectNoUnmockedRoutes(mock)
})
