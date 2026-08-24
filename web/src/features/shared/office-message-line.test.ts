// Shared line rendering (v15): the assignment PIC suffix must appear when the body
// carries `pic` but never duplicate a backend summary that already leads with it.
import { expect, test } from 'vitest'
import type { OfficeMessage } from '../../types'
import { externalActionTone, messageLine } from './office-message-line'

function msg(kind: OfficeMessage['kind'], body: OfficeMessage['body']): OfficeMessage {
  return { seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind, body }
}

test('assignment with pic appends the PIC suffix', () => {
  const line = messageLine(msg('assignment', {
    task_title: 'Ra mắt', summary: 'Phân công: a, b', step_count: 3, pic: 'noi-dung',
  }))
  expect(line).toBe('Ra mắt — Phân công: a, b (3 bước) — PIC: noi-dung')
})

test('assignment whose summary already leads with PIC does not duplicate it', () => {
  const line = messageLine(msg('assignment', {
    task_title: 'Ra mắt', summary: 'PIC: noi-dung — Phân công: a, b', step_count: 3,
    pic: 'noi-dung',
  }))
  expect(line).toBe('Ra mắt — PIC: noi-dung — Phân công: a, b (3 bước)')
})

test('assignment without pic renders exactly the pre-v15 line', () => {
  const line = messageLine(msg('assignment', {
    task_title: 'Ra mắt', summary: 'Phân công: a', step_count: 2,
  }))
  expect(line).toBe('Ra mắt — Phân công: a (2 bước)')
})

test('recover phase renders its label via the shared PHASE_LABEL', () => {
  const line = messageLine(msg('step_status', {
    task_title: 'T', step_title: 'S', status: 'started', phase: 'nho-tro-giup',
  }))
  expect(line).toContain('(nhờ trợ giúp)')
})

test('external_action renders "→ tool detail · outcome" (actor lives on the author chip) with a translated verdict', () => {
  const line = messageLine(msg('external_action', {
    actor: 'hr', tool: 'slack_send', action_type: 'send', outcome: 'allow', detail: '#general',
  }))
  expect(line).toBe('→ slack_send #general · ✓ cho phép')
})

test('external_action with a deny outcome and no detail omits the extra space', () => {
  const line = messageLine(msg('external_action', {
    actor: 'ops', tool: 'gh_pr_merge', action_type: 'write', outcome: 'deny',
  }))
  expect(line).toBe('→ gh_pr_merge · ✗ từ chối')
})

test('external_action with a non-allow/deny outcome passes the raw string through', () => {
  const line = messageLine(msg('external_action', {
    actor: 'ops', tool: 'jira_create', action_type: 'write', outcome: 'pending',
  }))
  expect(line).toBe('→ jira_create · pending')
})

test('externalActionTone maps allow/deny/other to ok/danger/neutral', () => {
  expect(externalActionTone('allow')).toBe('ok')
  expect(externalActionTone('deny')).toBe('danger')
  expect(externalActionTone('pending')).toBe('neutral')
  expect(externalActionTone(undefined)).toBe('neutral')
})

test('step_activity with a tool renders "đang gọi tool (count)"', () => {
  const line = messageLine(msg('step_activity', {
    agent: 'noi-dung', task: 't1', step: 's1',
    tool: 'web_search', count: 3, phase: 'calling-tool',
  }))
  expect(line).toBe('đang gọi web_search (3)')
})

test('step_activity in the writing phase renders the fixed writing line', () => {
  const line = messageLine(msg('step_activity', {
    agent: 'noi-dung', task: 't1', step: 's1', tool: '', count: 0, phase: 'writing',
  }))
  expect(line).toBe('đang viết…')
})

// The advisor's note IS its payload: the room shows the remark verbatim, so a missing
// `message` must degrade to an empty line rather than render "undefined" at the user.
test('advisor renders the note text itself', () => {
  expect(messageLine(msg('advisor', {
    task_id: 't1', step_id: 's1', severity: 'nit',
    message: 'Hai gói không cùng hạng.',
  }))).toBe('Hai gói không cùng hạng.')
  expect(messageLine(msg('advisor', { task_id: 't1', severity: 'concern' }))).toBe('')
})
