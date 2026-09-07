// The item model behind the bell: severity ranking, per-source mapping, and the
// fingerprint rule that decides when a dismissed row comes back.
import { beforeEach, expect, test, vi } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import type { FleetBudgetPayload, TeamAlert, TeamBoardLane } from '../../types'
import {
  buildAttentionItems,
  DISMISSED_STORAGE_KEY,
  isDismissed,
  readDismissed,
  writeDismissed,
  type Translate,
} from './attention-items'

// jsdom here exposes no localStorage; the repo's other storage-backed tests stub it the same way.
function installLocalStorage(): void {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size
    },
  })
}

const t: Translate = (key, params) => {
  let s: string = DICT.vi[key]
  for (const [k, v] of Object.entries(params ?? {})) s = s.replaceAll(`{${k}}`, String(v))
  return s
}

const LANES: TeamBoardLane[] = [
  {
    id: 'running',
    cards: [
      { task_id: 't1', title: 'Báo cáo quý', pic_id: 'ke-toan', room_id: 'room-1', status: 'running',
        created_at: '', steps_done: 1, steps_total: 3 },
      { task_id: 't2', title: 'Chiến dịch tết', pic_id: 'content', room_id: 'room 2', status: 'stalled',
        created_at: '', steps_done: 2, steps_total: 4, stalled_step: 'Viết bài' },
    ],
  },
]
const BUDGET: FleetBudgetPayload = {
  agents: [
    { agent_id: 'ke-toan', spent_usd: 2.5, cap_usd: 5, ratio: 0.5 },
    { agent_id: 'content', spent_usd: 4.2, cap_usd: 5, ratio: 0.84 },
    { agent_id: 'tro-ly-pm', spent_usd: 12, cap_usd: 10, ratio: 1.2 },
  ],
  total_spent_usd: 18.7, total_cap_usd: 20, ratio: 0.93,
}
const ALERTS: TeamAlert[] = [
  { kind: 'failing', agent_id: 'hr', message: '3 lần chạy gần nhất đều lỗi', severity: 'high' },
  { kind: 'deny_spike', agent_id: 'content', message: 'bị từ chối 4 lần', severity: 'warn' },
]

beforeEach(() => installLocalStorage())

test('ranks error > warning > info and keeps source order inside a band', () => {
  const items = buildAttentionItems(
    {
      approvals: [{ agent_id: 'content', id: 7, reason: 'Đăng bài', status: 'pending',
        created_at: '2026-09-07T01:00:00Z', action: { type: 'mcp_tool' } }],
      clarify: [{ id: 3, agent_id: 'hr', task_id: 't9', question: 'Chọn A hay B?', options: [],
        asked_at: '2026-09-07T02:00:00Z', expires_at: '' }],
      lanes: LANES,
      budget: BUDGET,
      coordinator: { alive: false, last_beat_ago_s: null, reason: 'no_heartbeat', hint: 'Chạy my-crew serve' },
      alerts: ALERTS,
      templates: [
        { agent_id: 'hr', role: 'hr', applied_version: 1, latest_version: 2, upgradable: true },
        { agent_id: 'pm', role: 'pm', applied_version: 2, latest_version: 2, upgradable: false },
      ],
    },
    t,
  )
  expect(items.map((i) => `${i.severity}:${i.id}`)).toEqual([
    'error:coordinator',
    'error:stalled:t2',
    'error:budget:tro-ly-pm',
    'error:alert:failing:hr',
    'warning:budget:content',
    'warning:alert:deny_spike:content',
    'warning:approval:content:7',
    'warning:clarify:3',
    'info:template:hr',
  ])
  // Each row deep-links to the surface that resolves it (room id URL-encoded).
  const byId = Object.fromEntries(items.map((i) => [i.id, i]))
  expect(byId['coordinator'].to).toBe('/system?tab=settings')
  expect(byId['coordinator'].detail).toBe('Chạy my-crew serve')
  expect(byId['stalled:t2'].to).toBe('/work/task/room%202')
  expect(byId['stalled:t2'].title).toBe('Việc kẹt: Chiến dịch tết')
  expect(byId['stalled:t2'].detail).toBe('Bước chết: Viết bài')
  expect(byId['budget:tro-ly-pm'].to).toBe('/team/tro-ly-pm?tab=budget')
  expect(byId['budget:tro-ly-pm'].title).toBe('tro-ly-pm vượt trần chi phí (120%)')
  expect(byId['budget:content'].title).toBe('content sắp chạm trần (84%)')
  expect(byId['budget:content'].detail).toBe('Đã tiêu $4.20 / trần $5.00')
  expect(byId['alert:failing:hr'].title).toBe('hr: đang lỗi liên tục')
  expect(byId['alert:failing:hr'].to).toBe('/team/hr')
  expect(byId['approval:content:7'].to).toBe('/work')
  expect(byId['clarify:3'].to).toBe('/chat')
  expect(byId['template:hr'].detail).toBe('v1 → v2')
})

test('quiet fleet → no items; alive coordinator and sub-80% budgets are silent', () => {
  expect(
    buildAttentionItems(
      {
        approvals: [], clarify: [], lanes: LANES.map((l) => ({ ...l, cards: l.cards.filter((c) => c.status !== 'stalled') })),
        budget: { ...BUDGET, agents: BUDGET.agents.slice(0, 1) },
        coordinator: { alive: true, last_beat_ago_s: 2, reason: '', hint: '' },
        alerts: [], templates: [],
      },
      t,
    ),
  ).toEqual([])
  expect(buildAttentionItems({}, t)).toEqual([])
})

test('a dismissal holds only while the fingerprint matches', () => {
  const near = buildAttentionItems({ budget: { ...BUDGET, agents: [BUDGET.agents[1]] } }, t)[0]
  writeDismissed({ [near.id]: near.fingerprint })
  expect(isDismissed(near, readDismissed())).toBe(true)
  // Spend creeping from 84% to 90% keeps the same band → still dismissed…
  const creep = buildAttentionItems(
    { budget: { ...BUDGET, agents: [{ ...BUDGET.agents[1], spent_usd: 4.5, ratio: 0.9 }] } }, t,
  )[0]
  expect(isDismissed(creep, readDismissed())).toBe(true)
  // …but crossing the cap is a new fingerprint, so the row comes back.
  const over = buildAttentionItems(
    { budget: { ...BUDGET, agents: [{ ...BUDGET.agents[1], spent_usd: 5.5, ratio: 1.1 }] } }, t,
  )[0]
  expect(isDismissed(over, readDismissed())).toBe(false)
})

test('readDismissed survives garbage and missing storage', () => {
  localStorage.setItem(DISMISSED_STORAGE_KEY, '{not json')
  expect(readDismissed()).toEqual({})
  localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify({ a: 'x', b: 3, c: null }))
  expect(readDismissed()).toEqual({ a: 'x' })
})
