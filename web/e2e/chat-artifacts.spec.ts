// The deliverables drawer, which moved out of the office side tabs into the chat thread
// when the hubs were redrawn. Same two things still need a real browser: the drawer is a
// lazy chunk (jsdom never loads it) and its transcript is a second fetch fired only when
// the 🔬 toggle is pressed, so a mocked-module unit test proves neither.
import { expect, test } from '@playwright/test'
import { DICT } from '../src/i18n/dictionary'
import { makeRoomEvents, mockOfficeApi } from './support/mock-api'

const ROOM = 'room-bao-cao-tuan'

test('10. drawer kết quả trong luồng chat: mở bước, bật 🔬 để xem từng event', async ({ page }) => {
  await mockOfficeApi(page, {
    roomEvents: { [ROOM]: makeRoomEvents(4, ROOM) },
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
  await page.goto(`/chat/${ROOM}`)
  await expect(page.locator('.chat-thread')).toBeVisible()

  // The drawer is off until asked for — the room index is a request the reader has not
  // paid for yet.
  await expect(page.locator('.artifact-drawer')).toHaveCount(0)
  await page.getByRole('button', { name: DICT.vi['artifacts.open'] }).click()
  await expect(page.locator('.artifact-drawer')).toBeVisible()

  // Step text first; the transcript is still a second fetch that has not happened.
  await page.locator('.artifact-step').click()
  await expect(page.locator('.artifact-text')).toContainText('Báo cáo tuần')
  await expect(page.locator('.artifact-event')).toHaveCount(0)

  await page.locator('.artifact-scope').click()
  await expect(page.locator('.artifact-transcript-meta')).toContainText('2')
  const events = page.locator('.artifact-event')
  await expect(events).toHaveCount(3)
  await expect(events.nth(1)).toContainText('web_search')
  await expect(events.nth(2)).toContainText('z-ai/glm-4.6')
  await expect(events.nth(2)).toContainText('120→45 tok')

  // A row expands to the raw event — the escape hatch when the summary is not enough.
  await expect(page.locator('.artifact-event-raw')).toHaveCount(0)
  await events.nth(1).locator('.artifact-event-line').click()
  await expect(page.locator('.artifact-event-raw')).toContainText('web_search')
})
