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
