// The failure → guidance table: every backend id maps to a why/next pair, an unknown
// id yields nothing, and the row/stall helpers pick the right case.
import { describe, expect, it } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import type { UiKey } from '../../i18n/dictionary'
import { failureCaseForRow, failureCaseForStall, failureGuidance } from './failure-guidance'

const t = (key: UiKey) => DICT.vi[key]

describe('failureGuidance', () => {
  it('answers every case the backend can emit, in both languages', () => {
    const ids = [
      'cost_cap', 'plan_mismatch', 'verification_exhausted', 'dead_step', 'step_exhausted',
      'external_deny', 'review_failed', 'step_failed', 'step_timeout',
    ]
    for (const id of ids) {
      const g = failureGuidance(t, id)
      expect(g, id).toBeDefined()
      expect(g?.why.length, id).toBeGreaterThan(0)
      expect(g?.next.length, id).toBeGreaterThan(0)
      expect(DICT.en[`failureGuide.${id}.why` as UiKey], id).toBeTruthy()
      expect(DICT.en[`failureGuide.${id}.next` as UiKey], id).toBeTruthy()
    }
  })
  it('yields nothing for an id this build does not know', () => {
    expect(failureGuidance(t, 'something_new')).toBeUndefined()
    expect(failureGuidance(t, undefined)).toBeUndefined()
    expect(failureGuidance(t, '')).toBeUndefined()
  })
})

describe('failureCaseForRow', () => {
  it('maps a denied gateway action, a failed review and a failed/timed-out step', () => {
    expect(failureCaseForRow('external_action', { outcome: 'deny' })).toBe('external_deny')
    expect(failureCaseForRow('external_action', { outcome: 'allow' })).toBeUndefined()
    expect(failureCaseForRow('review', { verdict: 'failed' })).toBe('review_failed')
    expect(failureCaseForRow('review', { verdict: 'passed' })).toBeUndefined()
    expect(failureCaseForRow('step_status', { status: 'failed' })).toBe('step_failed')
    expect(failureCaseForRow('step_status', { status: 'timeout' })).toBe('step_timeout')
    expect(failureCaseForRow('step_status', { status: 'started' })).toBeUndefined()
    expect(failureCaseForRow('ceo', {})).toBeUndefined()
  })
})

describe('failureCaseForStall', () => {
  it('reads a dead step as a step failure, otherwise as exhausted review rounds', () => {
    expect(failureCaseForStall(true)).toBe('step_failed')
    expect(failureCaseForStall(false)).toBe('verification_exhausted')
  })
})
