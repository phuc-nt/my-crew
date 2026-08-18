import { describe, expect, test } from 'vitest'
import type { ClarifyQuestion, FleetApprovalItem } from '../../../types'
import { buildPendingQueue, isExpired } from './pending-queue'

function approval(id: number, agent: string, at: string): FleetApprovalItem {
  return { id, agent_id: agent, reason: 'gửi email', status: 'pending', created_at: at, action: {} as never }
}

function question(id: number, agent: string, at: string, expires = ''): ClarifyQuestion {
  return {
    id, agent_id: agent, task_id: 't1', question: 'Dùng gói nào?',
    options: ['Free', 'Pro'], asked_at: at, expires_at: expires,
  }
}

describe('buildPendingQueue', () => {
  test('approvals and questions merge into one list, oldest first', () => {
    const out = buildPendingQueue(
      [approval(1, 'content', '2026-08-18T12:00:00Z')],
      [question(1, 'pm', '2026-08-18T10:00:00Z')],
    )
    expect(out.map((e) => e.kind)).toEqual(['question', 'approval'])
  })

  test('ids from the two sources never collide', () => {
    // Both id spaces start at 1, so a shared key would drop one of the two rows.
    const out = buildPendingQueue(
      [approval(1, 'content', '2026-08-18T10:00:00Z')],
      [question(1, 'pm', '2026-08-18T11:00:00Z')],
    )
    expect(new Set(out.map((e) => e.key)).size).toBe(2)
  })

  test('two agents can have the same approval id — the key stays unique', () => {
    const out = buildPendingQueue(
      [approval(1, 'content', '2026-08-18T10:00:00Z'), approval(1, 'pm', '2026-08-18T11:00:00Z')],
      [],
    )
    expect(new Set(out.map((e) => e.key)).size).toBe(2)
  })

  test('empty queues produce an empty list, not a crash', () => {
    expect(buildPendingQueue([], [])).toEqual([])
  })

  test('a missing timestamp sorts first rather than scrambling the order', () => {
    const out = buildPendingQueue([approval(1, 'a', '')], [question(1, 'b', '2026-08-18T10:00:00Z')])
    expect(out[0].kind).toBe('approval')
  })
})

describe('isExpired', () => {
  test('a question past its expiry is flagged — answering it would 409', () => {
    expect(isExpired(question(1, 'pm', '2026-08-18T10:00:00Z', '2026-08-18T11:00:00Z'),
      '2026-08-18T12:00:00Z')).toBe(true)
  })

  test('a live question is not flagged', () => {
    expect(isExpired(question(1, 'pm', '2026-08-18T10:00:00Z', '2026-08-18T13:00:00Z'),
      '2026-08-18T12:00:00Z')).toBe(false)
  })

  test('a question with no expiry never expires', () => {
    expect(isExpired(question(1, 'pm', '2026-08-18T10:00:00Z', ''), '2030-01-01T00:00:00Z')).toBe(false)
  })
})
