// Browser-side mock of the whole /api surface for the cockpit smoke tests. One
// dispatcher route ('**/api/**') so any endpoint we forgot is aborted loudly instead
// of leaking through the vite proxy to a real backend (fail-fast, secret-free CI).
//
// SSE: route.fulfill cannot hold a connection open, so the stream mock delivers the
// room's CURRENT event list and closes; `retry: 100` makes EventSource reconnect fast
// and replay (the hook dedups by seq). pushRoomEvents() appends events, so the next
// reconnect (~100ms) delivers them "live" — that is how the results-dot test injects
// a handoff after first render.
import type { Page } from '@playwright/test'
import type {
  OfficeMessage,
  RoomArtifactsPayload,
  StepArtifactPayload,
  StepTranscriptPayload,
  Workroom,
} from '../../src/types'
import { agentsFixture, assignStaffFixture, workroomsFixture } from '../fixtures/office-fixtures'

export interface OfficeApiMockOptions {
  workrooms?: Workroom[]
  /** Initial SSE replay per room id ('office' = the overview stream the 3D panel reads). */
  roomEvents?: Record<string, OfficeMessage[]>
  /** v82: delivered artifacts per room (default: none). */
  artifacts?: RoomArtifactsPayload
  /** v82: the one step artifact any /steps/{seq}/artifact hit returns. */
  stepArtifact?: StepArtifactPayload
  /** v82: the one process transcript any /steps/{seq}/transcript hit returns (absent → 404). */
  stepTranscript?: StepTranscriptPayload
  /** v82: POST /api/office/assign/preview response (composer sprint/team badge). */
  assignPreview?: Record<string, unknown>
}

export interface OfficeApiMock {
  /** Append events to a room's stream — delivered on the next EventSource reconnect (~100ms). */
  pushRoomEvents(roomId: string, events: OfficeMessage[]): void
}

function sseBody(events: OfficeMessage[]): string {
  const frames = events.map((e) => `id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`)
  return `retry: 100\n\n${frames.join('')}`
}

export async function mockOfficeApi(
  page: Page,
  opts: OfficeApiMockOptions = {},
): Promise<OfficeApiMock> {
  const streams = new Map<string, OfficeMessage[]>(Object.entries(opts.roomEvents ?? {}))
  if (!streams.has('office')) streams.set('office', makeOverviewEvents())

  // Predicate, not a glob: '**/api/**' would also swallow vite module URLs like
  // /src/api/client.ts and abort the app's own source files.
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const { pathname } = new URL(route.request().url())
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })

    if (pathname === '/api/setup/status') return json({ completed: true })
    if (pathname === '/api/me') return json({ authenticated: true, auth: 'off' })
    if (pathname === '/api/company')
      return json({
        name: 'ACME',
        coordinator_id: null,
        team_task_cap_usd: 1,
        team_task_concurrency: 1,
        team_task_auto_confirm: false,
      })
    if (pathname === '/api/agents') return json(agentsFixture)
    if (/^\/api\/agents\/[^/]+\/approvals$/.test(pathname))
      return json({ agent_id: pathname.split('/')[3], pending: [] })
    if (pathname === '/api/clarify/pending') return json({ questions: [] })
    if (pathname === '/api/team/alerts') return json({ alerts: [] })
    if (pathname === '/api/office/assign/staff') return json(assignStaffFixture)
    if (pathname === '/api/office/workrooms')
      return json({ rooms: opts.workrooms ?? workroomsFixture })
    if (pathname === '/api/team-tasks/board') return json({ lanes: [] })
    if (/^\/api\/team-tasks\/[^/]+\/cost$/.test(pathname))
      return json({
        task_id: pathname.split('/')[3],
        steps: [],
        total_cost_usd: 0.0042,
        total_input_tokens: 1000,
        total_output_tokens: 500,
      })
    if (pathname === '/api/schedule/upcoming') return json({ items: [] })
    if (pathname === '/api/health/coordinator')
      return json({ alive: true, last_beat_ago_s: 3, reason: '' })
    if (/^\/api\/office\/rooms\/[^/]+\/artifacts$/.test(pathname))
      return json(opts.artifacts ?? { tasks: [] })
    if (/^\/api\/office\/tasks\/[^/]+\/steps\/\d+\/artifact$/.test(pathname) && opts.stepArtifact)
      return json(opts.stepArtifact)
    if (/^\/api\/office\/tasks\/[^/]+\/steps\/\d+\/transcript$/.test(pathname)) {
      if (opts.stepTranscript) return json(opts.stepTranscript)
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'bước này chưa có transcript' }),
      })
    }
    if (pathname === '/api/office/assign/preview' && opts.assignPreview)
      return json(opts.assignPreview)
    if (/^\/api\/team-tasks\/[^/]+\/route$/.test(pathname))
      return json({ task_id: pathname.split('/')[3], mode: '', source: '', reason: '' })
    if (/^\/api\/team-tasks\/[^/]+\/metrics$/.test(pathname))
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'không thấy task' }),
      })

    const stream = pathname.match(/^\/api\/office\/rooms\/([^/]+)\/stream$/)
    if (stream) {
      const roomId = decodeURIComponent(stream[1])
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'cache-control': 'no-cache' },
        body: sseBody(streams.get(roomId) ?? []),
      })
    }

    console.log(`[mock-api] UNMOCKED ${route.request().method()} ${pathname}`)
    return route.abort()
  })

  return {
    pushRoomEvents(roomId, events) {
      streams.set(roomId, [...(streams.get(roomId) ?? []), ...events])
    },
  }
}

/** Overview ('office') stream: enough desk activity for the 3D panel to render staff. */
export function makeOverviewEvents(): OfficeMessage[] {
  return [
    {
      seq: 1,
      ts: '2026-07-31T09:00:00Z',
      author: 'ceo',
      kind: 'ceo',
      body: { text: 'Soạn báo cáo tuần cho sếp' },
    },
    {
      seq: 2,
      ts: '2026-07-31T09:00:05Z',
      author: 'coordinator',
      kind: 'assignment',
      body: { task_title: 'Soạn báo cáo tuần cho sếp', assigned_to: 'tro-ly-pm', step_count: 3 },
    },
    {
      seq: 3,
      ts: '2026-07-31T09:01:00Z',
      author: 'coordinator',
      kind: 'step_status',
      body: { step_title: 'Thu thập dữ liệu Jira', status: 'started', assigned_to: 'tro-ly-pm' },
    },
    {
      seq: 4,
      ts: '2026-07-31T09:02:00Z',
      author: 'coordinator',
      kind: 'step_status',
      body: { step_title: 'Phân tích số liệu', status: 'started', assigned_to: 'phan-tich-vien' },
    },
  ]
}

/**
 * Deterministic long room timeline — enough rows that the feed overflows its frame at
 * 1440×900 (the internal-scroll assertions need scrollHeight > clientHeight).
 */
export function makeRoomEvents(count: number): OfficeMessage[] {
  const events: OfficeMessage[] = [
    {
      seq: 1,
      ts: '2026-07-31T09:00:00Z',
      author: 'ceo',
      kind: 'ceo',
      body: { text: 'Soạn báo cáo tuần cho sếp, deadline thứ Sáu' },
    },
    {
      seq: 2,
      ts: '2026-07-31T09:00:05Z',
      author: 'coordinator',
      kind: 'assignment',
      body: { task_title: 'Soạn báo cáo tuần cho sếp', assigned_to: 'tro-ly-pm', step_count: 3 },
    },
  ]
  for (let seq = 3; seq <= count; seq += 1) {
    // One OLD handoff sits mid-history (regression for the v56 real-data bug: the SSE
    // replay of a room's past handoffs must never arm the results dot — "live" is the
    // event's ts vs room-open time, and this one is firmly in the past).
    if (seq === 20) {
      events.push({
        seq,
        ts: '2026-07-01T08:00:00Z',
        author: 'coordinator',
        kind: 'handoff',
        body: {
          step_title: 'Bàn giao lần trước',
          summary: 'Kết quả cũ đã bàn giao từ tuần trước.',
          assigned_to: 'tro-ly-pm',
        },
      })
      continue
    }
    events.push({
      seq,
      ts: `2026-07-31T09:${String(Math.min(59, seq)).padStart(2, '0')}:00Z`,
      author: 'coordinator',
      kind: 'step_status',
      body: {
        step_title: `Bước ${seq}: tổng hợp mục ${seq}`,
        status: seq % 2 ? 'started' : 'done',
        assigned_to: seq % 3 ? 'tro-ly-pm' : 'phan-tich-vien',
      },
    })
  }
  return events
}

/** A LIVE handoff for the results-dot test — stamped now, seq above the room's max. */
export function makeHandoff(seq: number): OfficeMessage {
  return {
    seq,
    ts: new Date().toISOString(),
    author: 'coordinator',
    kind: 'handoff',
    body: {
      step_title: 'Bàn giao báo cáo tuần',
      summary: 'Báo cáo tuần đã xong, đính kèm kết quả.',
      assigned_to: 'tro-ly-pm',
    },
  }
}
