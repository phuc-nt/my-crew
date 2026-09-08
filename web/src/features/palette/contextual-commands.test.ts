import { describe, expect, test } from 'vitest'
import { DICT, type UiKey } from '../../i18n/dictionary'
import { chatRoomOf, contextualCommands } from './contextual-commands'

const t = (key: UiKey, params?: Record<string, string | number>) =>
  Object.entries(params ?? {}).reduce(
    (s, [k, v]) => s.replaceAll(`{${k}}`, String(v)),
    DICT.vi[key] as string,
  )

describe('contextualCommands', () => {
  test('every item is a "here" row with a destination', () => {
    const items = contextualCommands('/work', '', t)
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) {
      expect(item.kind).toBe('context')
      expect(item.hint).toBe(DICT.vi['palette.here'])
      expect(item.to).toBeTruthy()
    }
  })

  test('the work hub lists its four tabs and the brief shortcut', () => {
    const tos = contextualCommands('/work', '', t).map((i) => i.to)
    expect(tos).toEqual([
      '/work?tab=board',
      '/work?tab=outputs',
      '/work?tab=schedule',
      '/work?tab=activity',
      '/chat',
    ])
    expect(contextualCommands('/work/task/room-9', '', t).map((i) => i.to)).toEqual(tos)
  })

  test('a chat room adds a link to its task; the overview and assistant do not', () => {
    expect(chatRoomOf('/chat')).toBeNull()
    expect(chatRoomOf('/chat/__assistant__')).toBeNull()
    expect(chatRoomOf('/chat/b%C3%A1o-c%C3%A1o')).toBe('báo-cáo')
    const overview = contextualCommands('/chat', '', t).map((i) => i.to)
    expect(overview).toEqual(['/chat', '/chat/__assistant__'])
    const room = contextualCommands('/chat/room-1', '', t)
    expect(room.map((i) => i.to)).toEqual(['/chat', '/chat/__assistant__', '/work/task/room-1'])
    expect(room[2].label).toBe(DICT.vi['palette.ctx.taskDetail'])
  })

  test('the team hub offers hiring, the system hub its tabs, unknown routes nothing', () => {
    expect(contextualCommands('/team', '', t)[0].to).toBe('/team?hire=1')
    expect(contextualCommands('/system', '', t)).toHaveLength(5)
    expect(contextualCommands('/nowhere', '', t)).toEqual([])
  })

  test('the query narrows the rows like every other palette source', () => {
    const items = contextualCommands('/system', 'kết nối', t)
    expect(items.map((i) => i.to)).toEqual(['/system?tab=connections'])
  })
})
