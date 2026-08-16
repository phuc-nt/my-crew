// v82 smoke: the two new CEO-facing surfaces — the composer's sprint/team routing badge
// (shown BEFORE confirm) and the ArtifactViewer's "Quá trình" transcript tab (high
// ui-mode only). Real browser because the badge depends on the preview POST round-trip
// and the tab on ui-mode persisted in localStorage — both invisible to jsdom smoke.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { makeRoomEvents, mockOfficeApi } from './support/mock-api'

const ROOM = 'room-bao-cao-tuan'

test('9. badge SPRINT hiện trong preview giao việc trước khi xác nhận', async ({ page }) => {
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(4) },
    assignPreview: {
      preview_text: 'KẾ HOẠCH: 1 bước, @tro-ly-pm làm thẳng',
      task_id: 't-sprint', plan_hash: 'h1', pic_id: 'tro-ly-pm',
      auto_confirmed: false, route_mode: 'sprint',
    },
  })
  await page.goto('/office')
  await expect(page.locator('.office-composer-bar')).toBeVisible()

  await page
    .getByPlaceholder(DICT.vi['assignComposer.placeholderNew'])
    .fill('@tro-ly-pm viết nháp thông báo nội bộ')
  // No active room → the button reads "Giao việc" (assign), not "Gửi" (send).
  await page.getByRole('button', { name: DICT.vi['assignComposer.assign'], exact: true }).click()

  const badge = page.locator('.office-mode-badge-sprint')
  await expect(badge).toBeVisible()
  await expect(badge).toHaveText(DICT.vi['assignComposer.modeSprint'])
})

test('10. tab Quá trình (chế độ nâng cao) tải transcript và render từng event', async ({ page }) => {
  // High ui-mode persisted BEFORE the app boots — the tab bar only renders when isHigh.
  await page.addInitScript(() => localStorage.setItem('ui-mode', 'high'))
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(4) },
    artifacts: {
      tasks: [{
        task_id: 't1', title: 'Soạn báo cáo tuần', pic_id: 'tro-ly-pm', status: 'done',
        steps: [{ step_id: 's1', title: 'Soạn nội dung', assigned_to: 'tro-ly-pm',
                  status: 'done', seq: 1, step_type: 'work' }],
      }],
    },
    stepArtifact: {
      task_id: 't1', step_title: 'Soạn nội dung',
      result_text: '# Báo cáo tuần', attempt: 'a1', self_check_failed: false,
    },
    stepTranscript: {
      task_id: 't1', step_id: 's1', seq: 1, attempts: 2,
      events: [
        { t: 'meta', agent: 'tro-ly-pm', attempt: 'a2' },
        { t: 'tool_call', name: 'web_search', args_head: 'q=doanh thu quý' },
        { t: 'llm_response', model: 'z-ai/glm-4.6', prompt_tokens: 120, completion_tokens: 45 },
      ],
    },
  })
  await page.goto(`/office?room=${ROOM}`)
  await expect(page.locator('.office-unified')).toBeVisible()

  // Results side tab → delivered step → viewer.
  await page.getByRole('button', { name: DICT.vi['officeSide.tabResults'] }).click()
  await page.locator('.artifact-item').click()
  await expect(page.locator('.artifact-drawer')).toBeVisible()

  // High mode: both tabs render; "Quá trình" swaps the body for the event list.
  await page.getByRole('tab', { name: DICT.vi['artifactViewer.tabProcess'] }).click()
  await expect(page.getByText(DICT.vi['transcriptTab.attempts'].replace('{n}', '2'))).toBeVisible()
  const events = page.locator('.transcript-event')
  await expect(events).toHaveCount(3)
  await expect(events.nth(1)).toContainText('web_search(q=doanh thu quý)')
  await expect(events.nth(2)).toContainText('z-ai/glm-4.6 · 120+45 tok')
})
