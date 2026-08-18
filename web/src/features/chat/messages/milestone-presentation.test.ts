import { describe, expect, test } from 'vitest'
import { isClamped, isDeliverable, milestoneText } from './milestone-presentation'

// Bodies below are shapes taken from the live fleet, shortened.
describe('milestone presentation', () => {
  test('the title is not re-printed in front of a message that already states it', () => {
    const body = {
      task_title: 'soạn email mời họp review quý 3 gồm thời gian, địa điểm và agenda 3 mục',
      message: "Đội đã nhận việc 'soạn email mời họp review quý 3 gồm thời gian, địa điểm và agenda 3 mục' (3 bước).",
      milestone: 'received',
    }
    const out = milestoneText(body)
    expect(out).toBe(body.message)
    expect(out.startsWith(body.task_title)).toBe(false)
  })

  test('a done milestone is flagged as the deliverable and kept whole', () => {
    const body = { milestone: 'done', message: '**Tiêu đề:** Mời họp Review Quý 3\n\nKính gửi anh/chị…' }
    expect(isDeliverable(body)).toBe(true)
    expect(milestoneText(body)).toBe(body.message)
  })

  test('status flavors are not deliverables', () => {
    for (const m of ['received', 'stuck', 'gave_up', 'follow_up']) {
      expect(isDeliverable({ milestone: m })).toBe(false)
    }
  })

  test('a body with no message falls back to the task title rather than rendering blank', () => {
    expect(milestoneText({ task_title: 'Báo cáo tuần' })).toBe('Báo cáo tuần')
  })

  test('an empty body renders as empty, not as "undefined"', () => {
    expect(milestoneText({})).toBe('')
  })

  test('a status milestone is clamped; the deliverable is not', () => {
    // Backend caps `message` at 501 chars and cuts mid-word, so a `stuck` notice is a
    // 500-char wall ending "…Google W…" — clamped. A `done` result keeps its height.
    expect(isClamped({ milestone: 'stuck', message: 'x'.repeat(501) })).toBe(true)
    expect(isClamped({ milestone: 'gave_up' })).toBe(true)
    expect(isClamped({ milestone: 'done', message: 'Kính gửi anh/chị…' })).toBe(false)
  })
})

describe('near-duplicate milestones', () => {
  // Seen in the live room 8251ebc8c8c0: a `done` and a `gave_up` milestone one second
  // apart, both carrying the SAME 501-char message ("Việc '…' KHÔNG LÀM ĐƯỢC: …").
  // They differ only in the `milestone` field, so a raw-body comparison sees two
  // distinct events while the reader sees the same wall of text printed twice.
  const message = "Việc 'Bên mình…' KHÔNG LÀM ĐƯỢC: bước 'Tóm tắt ngắn…' — không có người đủ công cụ"

  test('the same text under two flavors reads as one line for fold purposes', () => {
    expect(milestoneText({ milestone: 'done', message }))
      .toBe(milestoneText({ milestone: 'gave_up', message }))
  })

  test('a `done` whose own text says the work failed is NOT a deliverable', () => {
    // `message` here is the real "KHÔNG LÀM ĐƯỢC" notice. Trusting the flavor alone gave
    // this failure wall the full-height treatment meant for actual results.
    expect(isDeliverable({ milestone: 'done', message })).toBe(false)
    expect(isDeliverable({ milestone: 'gave_up', message })).toBe(false)
  })

  test('a `done` carrying real output is still a deliverable', () => {
    expect(isDeliverable({ milestone: 'done', message: 'Kính gửi Quý khách hàng,\n\nCảm ơn…' })).toBe(true)
  })
})
