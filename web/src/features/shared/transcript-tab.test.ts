// v82: pure summary lines for transcript events — the tab's rendering contract.
import { describe, expect, it } from 'vitest'
import { describeTranscriptEvent } from './transcript-tab'

describe('describeTranscriptEvent', () => {
  it('renders tool_call name + args head', () => {
    expect(describeTranscriptEvent({
      t: 'tool_call', name: 'web_search', args_head: 'q=giá vàng',
    })).toBe('web_search(q=giá vàng)')
  })

  it('renders tool_result content head', () => {
    expect(describeTranscriptEvent({
      t: 'tool_result', name: 'web_search', content_head: 'kết quả A',
    })).toBe('web_search → kết quả A')
  })

  it('renders llm_response model + token counts', () => {
    expect(describeTranscriptEvent({
      t: 'llm_response', model: 'z-ai/glm-4.6', prompt_tokens: 120, completion_tokens: 45,
    })).toBe('z-ai/glm-4.6 · 120+45 tok')
  })

  it('summarizes llm_request as role + message count, never inlining prompts', () => {
    const line = describeTranscriptEvent({
      t: 'llm_request', role: 'work', messages: [{ role: 'system', content: 'BÍ MẬT DÀI' }],
    })
    expect(line).toBe('work · 1 messages')
    expect(line).not.toContain('BÍ MẬT')
  })

  it('renders prefetch query list and truncates long heads', () => {
    expect(describeTranscriptEvent({
      t: 'prefetch', queries: ['giá vàng hôm nay', 'x'.repeat(100)], bytes: 2048,
    })).toBe(`web ×2: giá vàng hôm nay, ${'x'.repeat(60)}…`)
  })

  it('falls back to empty string for unknown kinds', () => {
    expect(describeTranscriptEvent({ t: 'loop_input' })).toBe('')
  })
})
