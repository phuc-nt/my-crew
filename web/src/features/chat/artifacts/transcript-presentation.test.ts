// Summary rules for raw recorder events, checked against real event shapes.
import { describe, expect, test } from 'vitest'
import type { StepTranscriptEvent } from '../../../types'
import { summarize, totalCost } from './transcript-presentation'

function ev(t: string, rest: Record<string, unknown> = {}): StepTranscriptEvent {
  return { t, ...rest } as StepTranscriptEvent
}

describe('event summaries', () => {
  test('an llm_request reports the model chain and message count, never the prompt', () => {
    // The real event measured 18,534 bytes; the summary must not carry the messages.
    const line = summarize(
      ev('llm_request', {
        role: 'plan',
        chain: ['deepseek/deepseek-v4-pro-0813'],
        messages: [{ role: 'system', content: 'x'.repeat(9000) }, { role: 'user', content: 'y' }],
      }),
    )
    expect(line.detail).toBe('plan · deepseek/deepseek-v4-pro-0813 · 2 msg')
    expect(line.detail).not.toContain('xxx')
  })

  test('an llm_response reports model, tokens and the first line of the content', () => {
    const line = summarize(
      ev('llm_response', {
        model: 'm1',
        prompt_tokens: 3215,
        completion_tokens: 820,
        content: 'dòng đầu\ndòng sau',
      }),
    )
    expect(line.detail).toBe('m1 · 3215→820 tok · dòng đầu')
  })

  test('a long single-line content is cut rather than wrapping the row', () => {
    const line = summarize(ev('llm_response', { model: 'm', content: 'a'.repeat(400) }))
    expect(line.detail.endsWith('…')).toBe(true)
    expect(line.detail.length).toBeLessThan(200)
  })

  test('an unknown kind still produces a row instead of vanishing from the log', () => {
    const line = summarize(ev('some_future_kind', { whatever: 1 }))
    expect(line.kind).toBe('some_future_kind')
    expect(line.raw).toContain('some_future_kind')
  })

  test('the raw JSON is always available for the expandable detail', () => {
    const line = summarize(ev('outcome', { status: 'done', pause_reason: '' }))
    expect(line.detail).toBe('done')
    expect(JSON.parse(line.raw).status).toBe('done')
  })
})

describe('cost', () => {
  test('cost sums only events that report one', () => {
    const events = [
      ev('meta'),
      ev('llm_response', { cost_usd: 0.000841957 }),
      ev('llm_response', { cost_usd: 0.002 }),
    ]
    expect(totalCost(events)).toBeCloseTo(0.002841957, 9)
  })

  test('a step with no priced events totals zero rather than NaN', () => {
    expect(totalCost([ev('meta'), ev('prefetch', { bytes: 10 })])).toBe(0)
  })
})
