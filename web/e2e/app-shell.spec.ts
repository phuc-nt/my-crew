// Phase 1 shell smoke: the 5-hub nav replaces the 7-primary + 9-advanced rows, and the
// approvals badge reads the fleet index in ONE request instead of fanning out per agent.
//
// Real browser because both facts are routing/render behaviour the unit tests cannot see:
// the nav is driven by react-router NavLink state, and the badge count comes from a
// TanStack Query fetch that only fires once the provider tree is mounted.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { mockOfficeApi } from './support/mock-api'

const HUB_KEYS = ['hub.chat', 'hub.office', 'hub.work', 'hub.team', 'hub.system'] as const

test('11. shell 5 hub: nav đủ 5 mục, "/" chuyển về /chat', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/')

  // Index route redirects to the new home hub rather than rendering a blank shell.
  await expect(page).toHaveURL(/\/chat$/)

  const nav = page.locator('.app-nav-primary')
  await expect(nav).toBeVisible()
  for (const key of HUB_KEYS) {
    await expect(nav.getByRole('link', { name: DICT.vi[key], exact: false })).toBeVisible()
  }
  // The old advanced nav row is gone as a navigation concept.
  await expect(page.locator('.app-nav-advanced')).toHaveCount(0)
})

test('12. badge duyệt trên hub Công việc đếm từ index approvals toàn fleet', async ({ page }) => {
  await mockOfficeApi(page, {
    pendingApprovals: [
      {
        agent_id: 'content',
        id: 1,
        reason: 'Đăng bài blog',
        status: 'pending',
        created_at: '2026-08-18T10:00:00Z',
        action: { type: 'mcp_tool', server: 'blog', tool: 'post' },
      },
      {
        agent_id: 'tro-ly-pm',
        id: 2,
        reason: 'Gửi email khách',
        status: 'pending',
        created_at: '2026-08-18T10:05:00Z',
        action: { type: 'email_send', to: ['a@b.c'], subject: 'Xin chào' },
      },
    ],
  })
  await page.goto('/chat')

  // Two rows across two different agents → one badge reading 2, on the Work hub only.
  const workLink = page.locator('.app-nav-primary').getByRole('link', { name: DICT.vi['hub.work'] })
  await expect(workLink.locator('.nav-badge')).toHaveText('2')
  await expect(page.locator('.app-nav-primary .nav-badge')).toHaveCount(1)
})

test('13. không có approval nào thì badge không hiện', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/chat')

  await expect(page.locator('.app-nav-primary')).toBeVisible()
  await expect(page.locator('.nav-badge')).toHaveCount(0)
})

// The attention bell is shell chrome too: it merges signals every hub already fetches
// into one badge, and its dismissals live in localStorage — a real browser is the only
// place both the persistence and the deep-link navigation can be checked together.
test('14. chuông chú ý: badge đếm lỗi+cảnh báo, hàng xếp nặng trước, bấm hàng nhảy đúng chỗ', async ({ page }) => {
  await mockOfficeApi(page, {
    pendingApprovals: [
      {
        agent_id: 'content',
        id: 1,
        reason: 'Đăng bài blog',
        status: 'pending',
        created_at: '2026-09-07T10:00:00Z',
        action: { type: 'mcp_tool', server: 'blog', tool: 'post' },
      },
    ],
    coordinatorHealth: { alive: false, last_beat_ago_s: null, reason: 'no_heartbeat', hint: 'Chạy my-crew serve' },
    templateStatus: [{ agent_id: 'hr', role: 'hr', applied_version: 1, latest_version: 2, upgradable: true }],
  })
  await page.goto('/chat')

  // error (coordinator) + warning (approval) = 2; the info row (template) is not counted.
  await expect(page.getByTestId('attention-badge')).toHaveText('2')
  await page.getByRole('button', { name: DICT.vi['attention.bellLabel'].replace('{n}', '2') }).click()
  const panel = page.getByTestId('attention-panel')
  await expect(panel.locator('.attention-item')).toHaveCount(3)
  await expect(panel.locator('.attention-item').nth(0)).toHaveAttribute('data-severity', 'error')
  await expect(panel.locator('.attention-item').nth(2)).toHaveAttribute('data-severity', 'info')

  await panel.locator('.attention-item').nth(0).getByRole('link').click()
  await expect(page).toHaveURL(/\/system\?tab=settings$/)
  await expect(panel).toHaveCount(0)
})

test('15. bỏ qua một mục giữ qua reload; mục đổi nội dung thì hiện lại', async ({ page }) => {
  await mockOfficeApi(page, {
    teamAlerts: [
      { kind: 'failing', agent_id: 'hr', message: 'lỗi 3 lần', severity: 'high' },
      { kind: 'deny_spike', agent_id: 'content', message: 'từ chối 4 lần', severity: 'warn' },
    ],
  })
  await page.goto('/chat')
  await expect(page.getByTestId('attention-badge')).toHaveText('2')
  await page.getByRole('button', { name: DICT.vi['attention.bellLabel'].replace('{n}', '2') }).click()
  const panel = page.getByTestId('attention-panel')
  await panel.locator('.attention-item').nth(0).getByRole('button', { name: DICT.vi['attention.dismiss'] }).click()
  await expect(page.getByTestId('attention-badge')).toHaveText('1')
  await expect(panel.getByText(DICT.vi['attention.hiddenN'].replace('{n}', '1'))).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('attention-badge')).toHaveText('1')

  // Same alert id, new message → new fingerprint → back in the list.
  await mockOfficeApi(page, {
    teamAlerts: [
      { kind: 'failing', agent_id: 'hr', message: 'lỗi 5 lần', severity: 'high' },
      { kind: 'deny_spike', agent_id: 'content', message: 'từ chối 4 lần', severity: 'warn' },
    ],
  })
  await page.reload()
  await expect(page.getByTestId('attention-badge')).toHaveText('2')
})

test('16. phím tắt: ? mở bảng, g w nhảy hub, gõ trong ô nhập không kích hoạt', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/chat')
  await expect(page.locator('.app-nav-primary')).toBeVisible()

  await page.keyboard.press('Shift+?')
  const card = page.getByTestId('shortcuts-help')
  await expect(card).toBeVisible()
  await expect(card).toContainText(DICT.vi['shortcuts.goTo'].replace('{hub}', DICT.vi['hub.work']))
  await page.keyboard.press('Escape')
  await expect(card).toHaveCount(0)

  await page.keyboard.press('g')
  await page.keyboard.press('w')
  await expect(page).toHaveURL(/\/work$/)

  // The ⌨ chip is the discoverable route to the same card.
  await page.getByRole('button', { name: DICT.vi['shortcuts.button'] }).click()
  await expect(card).toBeVisible()
  await page.keyboard.press('Escape')
})

test('61. banner "bản mới đã cài" hiện khi /health đổi version giữa hai lần poll, "Để sau" ẩn đi', async ({ page }) => {
  await page.clock.install()
  await mockOfficeApi(page, { healthVersions: ['0.18.0', '0.19.0'] })
  await page.goto('/chat')
  await expect(page.locator('.app-nav-primary')).toBeVisible()
  await expect(page.getByTestId('update-banner')).toHaveCount(0)

  // The banner polls once a minute; jump past one interval instead of waiting it out.
  await page.clock.fastForward(61_000)
  const banner = page.getByTestId('update-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toContainText(DICT.vi['updateBanner.text'].replace('{version}', '0.19.0'))
  await expect(banner.getByRole('button', { name: DICT.vi['updateBanner.reload'] })).toBeVisible()

  await banner.getByRole('button', { name: DICT.vi['updateBanner.dismiss'] }).click()
  await expect(page.getByTestId('update-banner')).toHaveCount(0)
  // A further poll of the same version does not bring it back.
  await page.clock.fastForward(61_000)
  await expect(page.getByTestId('update-banner')).toHaveCount(0)
})
