// Phase 4 team hub smoke: the roster, the inline hire panel, and the eight-tab agent page
// that replaced seven separate top-level routes.
//
// Real browser because all three facts are routing/lazy-loading behaviour the unit tests
// cannot see: the hire panel and the detail page each arrive as their own chunk, and the
// tab state lives in the URL rather than component state.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { agentsFixture } from './fixtures/office-fixtures'
import { mockOfficeApi } from './support/mock-api'

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
