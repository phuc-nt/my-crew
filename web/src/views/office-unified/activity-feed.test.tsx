// v54 P3: feed filter chips [Tất cả | Bước | Ra ngoài] — verifies the filter narrows the
// SAME props-supplied stream (no re-fetch, no re-sort) and that external_action renders
// as "actor → tool detail · outcome".
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { LanguageProvider } from '../../i18n/language-context'
import type { OfficeMessage } from '../../types'
import { ActivityFeed } from './activity-feed'

function msg(kind: OfficeMessage['kind'], body: OfficeMessage['body'], seq: number): OfficeMessage {
  return { seq, ts: 't', author: body.assigned_to ?? body.actor ?? 'coordinator', kind, body }
}

const MESSAGES: OfficeMessage[] = [
  msg('step_status', { task_title: 'T1', step_title: 'draft', status: 'started', assigned_to: 'hr' }, 1),
  msg('external_action', {
    actor: 'hr', tool: 'slack_send', action_type: 'send', outcome: 'allow', detail: '#general',
  }, 2),
  msg('external_action', {
    actor: 'ops', tool: 'gh_pr_merge', action_type: 'write', outcome: 'deny', detail: 'PR#3',
  }, 3),
  msg('milestone', { task_title: 'T1', message: 'done' }, 4),
]

function renderFeed(messages: OfficeMessage[] = MESSAGES) {
  return render(
    <LanguageProvider>
      <ActivityFeed messages={messages} connected errored={false} />
    </LanguageProvider>,
  )
}

test('default filter (Tất cả) shows every kind', () => {
  renderFeed()
  expect(screen.getByText(/T1 \/ draft: started/)).toBeTruthy()
  expect(screen.getByText(/hr → slack_send #general · ✓ cho phép/)).toBeTruthy()
  expect(screen.getByText(/ops → gh_pr_merge PR#3 · ✗ từ chối/)).toBeTruthy()
  expect(screen.getByText(/T1: done/)).toBeTruthy()
})

test('"Ra ngoài" filter shows only external_action lines', () => {
  renderFeed()
  fireEvent.click(screen.getByText('Ra ngoài'))
  expect(screen.getByText(/hr → slack_send #general · ✓ cho phép/)).toBeTruthy()
  expect(screen.getByText(/ops → gh_pr_merge PR#3 · ✗ từ chối/)).toBeTruthy()
  expect(screen.queryByText(/T1 \/ draft: started/)).toBeNull()
  expect(screen.queryByText(/T1: done/)).toBeNull()
})

test('"Bước" filter shows only step_status lines', () => {
  renderFeed()
  fireEvent.click(screen.getByText('Bước'))
  expect(screen.getByText(/T1 \/ draft: started/)).toBeTruthy()
  expect(screen.queryByText(/hr → slack_send/)).toBeNull()
  expect(screen.queryByText(/T1: done/)).toBeNull()
})

test('filter chips carry aria-pressed reflecting the active filter', () => {
  renderFeed()
  const allChip = screen.getByText('Tất cả')
  const externalChip = screen.getByText('Ra ngoài')
  expect(allChip.getAttribute('aria-pressed')).toBe('true')
  expect(externalChip.getAttribute('aria-pressed')).toBe('false')
  fireEvent.click(externalChip)
  expect(externalChip.getAttribute('aria-pressed')).toBe('true')
  expect(allChip.getAttribute('aria-pressed')).toBe('false')
})

test('"Ra ngoài" filter with no external events shows the external empty state', () => {
  renderFeed([msg('milestone', { task_title: 'T1', message: 'done' }, 1)])
  fireEvent.click(screen.getByText('Ra ngoài'))
  expect(screen.getByText('Chưa có hành động ra ngoài nào.')).toBeTruthy()
})
