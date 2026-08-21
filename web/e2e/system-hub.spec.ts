// Phase 6 system hub smoke: the five tabs that absorbed /settings, /connections,
// /company-docs and /captures, plus the redirect table that keeps every pre-redesign
// URL resolving.
//
// Real browser because both facts are routing facts. Tab state lives in the URL, so a
// deep link has to mount the right tab on a cold load — a unit test rendering the
// component directly would pass even if the param wiring were broken. And the redirects
// only exist in the route table; nothing else in the app can prove an old bookmark lands.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { mockOfficeApi } from './support/mock-api'

test('20. hub Hệ thống mở tab Cài đặt mặc định và tab nằm trong URL', async ({ page }) => {
  await mockOfficeApi(page)
  await page.goto('/system')

  await expect(page.getByTestId('system-page')).toBeVisible()
  // No ?tab= on a bare /system, so settings is the tab that must be showing.
  await expect(page.getByRole('button', { name: DICT.vi['systemHub.tabSettings'] }))
    .toHaveClass(/tab-active/)

  await page.getByRole('button', { name: DICT.vi['systemHub.tabInsights'] }).click()
  await expect(page).toHaveURL(/tab=insights/)
  await expect(page.getByText(DICT.vi['systemInsights.budgetTitle'])).toBeVisible()
})

test('21. tab Số liệu hiện chi tiêu toàn đội và mỗi dòng link sang trang nhân sự', async ({ page }) => {
  await mockOfficeApi(page, {
    fleetBudget: {
      agents: [
        { agent_id: 'ke-toan', spent_usd: 2.5, cap_usd: 5, ratio: 0.5 },
        // Over cap: the ratio cell is the one thing on this tab that changes colour.
        { agent_id: 'tro-ly-pm', spent_usd: 12, cap_usd: 10, ratio: 1.2 },
      ],
      total_spent_usd: 14.5,
      total_cap_usd: 15,
      ratio: 0.97,
    },
  })
  await page.goto('/system?tab=insights')

  await expect(page.getByRole('row')).toHaveCount(3) // header + one row per agent
  // Over-cap is the one state this table colours, so exactly one cell must carry it.
  await expect(page.locator('td.error')).toHaveCount(1)
  // The breakdown lives on the agent's own page, so the row must carry a link there.
  await expect(page.getByRole('link', { name: 'ke-toan' }))
    .toHaveAttribute('href', '/team/ke-toan?tab=budget')
})

test('22. tab Nhật ký kiểm tra liệt kê lần chạy và lọc theo task nằm trong URL', async ({ page }) => {
  await mockOfficeApi(page, {
    captures: [
      {
        attempt_id: 'a-1', task_id: 't-1', step_id: 's-1', agent_id: 'ke-toan',
        engine: 'claude', status: 'ok', step_type: 'analyze', review_round: 0,
        cost_usd: 0.2, cost_source: 'measured', input_tokens: 100, output_tokens: 50,
        started_at: '2026-08-19T01:00:00Z', ended_at: '2026-08-19T01:01:00Z',
        ts: '2026-08-19T01:01:00Z', duration_ms: 60_000, error: '',
      },
    ],
  })
  await page.goto('/system?tab=audit&task_id=t-1')

  await expect(page.locator('.captures-table tbody tr')).toHaveCount(1)
  await expect(page.getByText('ke-toan')).toBeVisible()
  // The task filter arrived from the URL and shows as a removable chip — that is what
  // makes "open the audit log for THIS task" a shareable link from the task page.
  const chip = page.getByRole('button', { name: /t-1/ })
  await expect(chip).toBeVisible()
  await chip.click()
  await expect(page).not.toHaveURL(/task_id/)
})

test('23. mọi URL trước khi thiết kế lại vẫn mở được, không 404', async ({ page }) => {
  await mockOfficeApi(page)
  const redirects: [string, RegExp][] = [
    ['/settings', /\/system\?tab=settings/],
    ['/connections', /\/system\?tab=connections/],
    ['/company-docs', /\/system\?tab=company/],
    ['/captures', /\/system\?tab=audit/],
    ['/outputs', /\/work\?tab=outputs/],
    ['/company-activity', /\/work\?tab=activity/],
    ['/approvals', /\/work$/],
    ['/create', /\/team$/],
    // The agent id rides in the path, so this one must keep it rather than drop to /team.
    ['/agents/ke-toan', /\/team\/ke-toan\?tab=profile/],
    ['/cost', /\/team$/],
    ['/office/3d', /\/office$/],
    ['/khong-co-trang-nay', /\/chat$/],
  ]
  for (const [from, to] of redirects) {
    await page.goto(from)
    await expect(page, `${from} phải chuyển hướng`).toHaveURL(to)
  }
})

// v91 P5-D: autopilot and concurrency became editable here. Both save through the same
// load-modify-save route, so what matters is that a write carries the OTHER fields
// unchanged — a save that dropped them would silently reset the fleet's cap or its
// auto-confirm flag while the CEO was only nudging one number.
test('24. bật autopilot ghi đúng payload và giữ nguyên các cài đặt khác', async ({ page }) => {
  const mock = await mockOfficeApi(page, {
    company: { team_task_cap_usd: 7, team_task_auto_confirm: true, team_task_concurrency: 3 },
  })
  await page.goto('/system')

  const autopilot = page.locator('.mode-toggle', { hasText: DICT.vi['settings.autopilotLabel'] })
  await autopilot.locator('input[type="checkbox"]').click()

  await expect.poll(() => mock.companyWrites).toEqual([
    {
      name: 'ACME',
      coordinator_id: null,
      team_task_cap_usd: 7,
      team_task_auto_confirm: true,
      autopilot: true,
    },
  ])
  await expect(autopilot.locator('input[type="checkbox"]')).toBeChecked()
})

test('25. sửa số việc chạy song song ghi giá trị mới, bỏ qua giá trị ngoài biên', async ({
  page,
}) => {
  const mock = await mockOfficeApi(page, { company: { team_task_concurrency: 1 } })
  await page.goto('/system')

  const concurrency = page.locator('#settings-concurrency')
  await concurrency.fill('4')
  await expect.poll(() => mock.companyWrites.at(-1)?.team_task_concurrency).toBe(4)
  await expect(concurrency).toHaveValue('4')

  // Out of range is refused client-side — no write at all, rather than a rejected one.
  const before = mock.companyWrites.length
  await concurrency.fill('99')
  await expect.poll(() => mock.companyWrites.length).toBe(before)
})
