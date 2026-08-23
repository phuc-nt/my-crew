import { describe, expect, test } from 'vitest'
import {
  commandItems,
  fuzzyMatches,
  historyItems,
  refToRoom,
  stripHighlights,
} from './palette-items'

describe('fuzzyMatches', () => {
  test('matches an in-order subsequence, ignoring spaces and case', () => {
    expect(fuzzyMatches('vnph', 'Văn phòng')).toBe(true)
    expect(fuzzyMatches('V P', 'Văn phòng')).toBe(true)
    expect(fuzzyMatches('gnhp', 'Văn phòng')).toBe(false)
  })

  test('an empty query matches everything, so the palette opens showing its full menu', () => {
    expect(fuzzyMatches('', 'anything')).toBe(true)
    expect(fuzzyMatches('   ', 'anything')).toBe(true)
  })

  test('does not fold diacritics — see the note on the function', () => {
    expect(fuzzyMatches('cai dat', 'Cài đặt')).toBe(false)
    // 'o' does not match 'ò', which is why the label's own accented run is unreachable
    // by an unaccented query. The nav labels are short; history search covers the rest.
    expect(fuzzyMatches('phong', 'Văn phòng')).toBe(false)
  })
})

describe('history hits', () => {
  // Verbatim shape from GET /api/search?q=bao cao on the live fleet.
  const hit = (ref: string) => ({
    excerpt: 'điều tra về gpt 5.6 — Tổng hợp và »báo« »cáo« kết quả',
    source: 'step' as const,
    ref,
    agent_id: 'default',
    ts: '2026-07-11T01:50:17.652428+00:00',
  })

  test('strips the FTS5 snippet markers instead of rendering them', () => {
    expect(stripHighlights('và »báo« »cáo« kết quả')).toBe('và báo cáo kết quả')
  })

  test('a ref addresses a task and a step; only the task is a room', () => {
    expect(refToRoom('10fbf98bafa6:52')).toBe('10fbf98bafa6')
  })

  test('links a hit whose room is still live', () => {
    const [item] = historyItems([hit('10fbf98bafa6:52')], new Set(['10fbf98bafa6']))
    expect(item.to).toBe('/chat/10fbf98bafa6')
    expect(item.label).not.toContain('»')
  })

  test('a hit whose room was pruned stays listed but has no destination', () => {
    // Real case: the FTS5 index outlives the workroom projection, and /api/office/messages
    // 404s for this task. A link would open a permanently empty thread.
    const [item] = historyItems([hit('3e4a8d64ea20:325')], new Set(['10fbf98bafa6']))
    expect(item.to).toBeUndefined()
    expect(item.label).toContain('báo')
  })
})

describe('commandItems', () => {
  const commands = [
    { id: 'get_status', description: 'Xem trạng thái cả đội', readonly: true,
      example: 'get_status' },
    { id: 'create_agent', description: 'Tạo một nhân sự ảo (agent) mới', readonly: false,
      example: 'create_agent' },
  ]

  test('a command carries no destination — picking it seeds the assistant composer', () => {
    const items = commandItems(commands, '')
    expect(items).toHaveLength(2)
    expect(items.every((i) => i.to === undefined)).toBe(true)
  })

  test('matches on the id as well as the description', () => {
    expect(commandItems(commands, 'create_a').map((i) => i.id)).toEqual(['create_agent'])
    expect(commandItems(commands, 'trạng').map((i) => i.id)).toEqual(['get_status'])
  })
})
