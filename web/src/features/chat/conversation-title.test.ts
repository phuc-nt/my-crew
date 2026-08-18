import { describe, expect, test } from 'vitest'
import { shortTitle } from './conversation-title'

describe('shortTitle', () => {
  test('a short title is untouched', () => {
    expect(shortTitle('Soạn email mời họp')).toBe('Soạn email mời họp')
  })

  test('a long title is cut at a word boundary with an ellipsis', () => {
    // A real title from the fleet: 120+ chars of raw brief.
    const real =
      'Bên mình đang cân nhắc đổi bộ công cụ làm việc cho nhóm nội dung nên cần một bản tóm tắt ngắn về chi phí. Hiện tại nhóm'
    const out = shortTitle(real)
    expect(out.length).toBeLessThanOrEqual(53)
    expect(out.endsWith('…')).toBe(true)
    expect(out).not.toMatch(/\s…$/) // no dangling space before the ellipsis
    expect(real.startsWith(out.slice(0, -1))).toBe(true) // a true prefix, nothing invented
  })

  test('a long unbroken run is cut hard rather than collapsing to nothing', () => {
    const out = shortTitle('x'.repeat(80))
    expect(out).toBe(`${'x'.repeat(52)}…`)
  })

  test('collapsed whitespace keeps the line single-line', () => {
    expect(shortTitle('Soạn   tin\n nhắn')).toBe('Soạn tin nhắn')
  })
})
