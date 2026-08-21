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
  CaptureRow,
  ConnectionCard,
  FleetApprovalItem,
  FleetBudgetPayload,
  OfficeMessage,
  OutputItem,
  RoomArtifactsPayload,
  ScheduleItem,
  StaffTemplate,
  StepArtifactPayload,
  StepTranscriptPayload,
  TeamBoardLane,
  TeamTaskActionResult,
  TeamTaskMetricsPayload,
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
  /** Fleet-wide spend behind the system hub's Insights tab (default: an empty fleet). */
  fleetBudget?: FleetBudgetPayload
  /** Connection cards behind the system hub's Connections tab (default: none). */
  connections?: ConnectionCard[]
  /** Attempt rows behind the system hub's Audit tab (default: none). */
  captures?: CaptureRow[]
  /** Staff templates behind the team hub's hire panel (default: one office role). */
  staffTemplates?: StaffTemplate[]
  /** Profiles on disk that fell out of the registry — the recovery list (default: none). */
  unregistered?: { id: string; domain: string }[]
  /** Rows for the fleet approvals index — drives the shell's nav badge count. */
  pendingApprovals?: FleetApprovalItem[]
  /** Agent questions behind the chat hub's pending column. */
  clarifyQuestions?: unknown[]
  /** The ops catalog the assistant pane and the palette both read. */
  opsCommands?: { id: string; description: string; readonly: boolean }[]
  /** Reply for POST /api/ops/chat. A number instead delays the reply that many ms,
   *  which is how the "still working" indicator is exercised. */
  opsReply?: string
  opsReplyDelayMs?: number
  /** Lanes for the work hub's task board (default: none — the board renders empty). */
  boardLanes?: TeamBoardLane[]
  /** Rows for the outputs list (default: none). */
  outputs?: OutputItem[]
  /** Next cron fires behind the work hub's schedule tab (default: none). */
  scheduleItems?: ScheduleItem[]
  /** Per-task metrics; absent → the endpoint 404s, which is a real pre-v82 task. */
  taskMetrics?: TeamTaskMetricsPayload
  /** Hits for GET /api/search — the palette's history source. */
  searchHits?: { excerpt: string; source: string; ref: string; agent_id: string; ts: string }[]
  /** v88 P3: the refreshed-task shape every retry/accept/drop/cancel call returns
   *  (default: a plain "back to open" / "cancelled" shape — see the dispatcher below). */
  teamTaskActionResult?: TeamTaskActionResult
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
    // Fleet-wide index behind the shell's approvals badge. Served from `opts.pendingApprovals`
    // so a spec can assert the badge count; empty by default, matching the per-agent route above.
    if (pathname === '/api/approvals/pending') {
      const pending = opts.pendingApprovals ?? []
      return json({ pending, count: pending.length })
    }
    if (pathname === '/api/clarify/pending')
      return json({ questions: opts.clarifyQuestions ?? [] })
    if (pathname === '/api/ops/chat/available') return json({ available: true })
    if (pathname === '/api/ops/chat/commands') return json({ commands: opts.opsCommands ?? [] })
    if (pathname === '/api/ops/chat' && route.request().method() === 'POST') {
      // The real engine takes seconds; the delay makes that latency assertable instead
      // of a race the spec would have to sleep through.
      if (opts.opsReplyDelayMs) await new Promise((r) => setTimeout(r, opts.opsReplyDelayMs))
      return json({ reply: opts.opsReply ?? 'Đội hiện có 11 agent', agent_id: 'admin' })
    }
    if (pathname === '/api/search') return json({ hits: opts.searchHits ?? [] })
    // The office health strip reads this and swallows a failure, so an unmocked call was
    // invisible in the UI — but it logged UNMOCKED on every office run, which is exactly
    // the signal a genuinely missing route needs to stand out.
    if (pathname === '/api/budget')
      return json(
        opts.fleetBudget ?? { agents: [], total_spent_usd: 0, total_cap_usd: 0, ratio: 0 },
      )
    if (pathname === '/api/connections')
      return json({ cards: opts.connections ?? [], needs_restart: false })
    if (pathname === '/api/health/integrations') return json({ checks: [], checked_at: 0 })
    if (pathname === '/api/team/alerts') return json({ alerts: [] })
    if (pathname === '/api/office/assign/staff') return json(assignStaffFixture)
    if (pathname === '/api/office/workrooms')
      return json({ rooms: opts.workrooms ?? workroomsFixture })
    if (pathname === '/api/team-tasks/board') return json({ lanes: opts.boardLanes ?? [] })
    if (/^\/api\/team-tasks\/[^/]+\/cost$/.test(pathname))
      return json({
        task_id: pathname.split('/')[3],
        steps: [],
        total_cost_usd: 0.0042,
        total_input_tokens: 1000,
        total_output_tokens: 500,
      })
    // v88 P3: one-click unstick (retry/accept/drop) + cancel — every mutation returns
    // the task's refreshed shape; `opts.teamTaskActionResult` lets a spec override it
    // (e.g. to prove the card leaves the board after cancel), default is a plain
    // "back to open" shape covering the common happy-path assertion.
    if (/^\/api\/team-tasks\/[^/]+\/steps\/[^/]+\/(retry|accept|drop)$/.test(pathname)) {
      const taskId = pathname.split('/')[3]
      return json(
        opts.teamTaskActionResult ?? {
          task_id: taskId, title: 'Việc', status: 'open', pic_id: '', room_id: taskId, steps: [],
        },
      )
    }
    if (/^\/api\/team-tasks\/[^/]+\/cancel$/.test(pathname)) {
      const taskId = pathname.split('/')[3]
      return json(
        opts.teamTaskActionResult ?? {
          task_id: taskId, title: 'Việc', status: 'cancelled', pic_id: '', room_id: taskId,
          steps: [],
        },
      )
    }
    if (pathname === '/api/schedule/upcoming') return json({ items: opts.scheduleItems ?? [] })
    // The outputs tab carries its filters in the query string, so match the path only.
    if (pathname === '/api/outputs') return json({ items: opts.outputs ?? [], truncated: false })
    if (pathname === '/api/company/activity')
      return json({ items: [], total: 0, truncated: false, skipped: [] })
    // The desk inspector opens on a click and immediately asks for that agent's status;
    // without this the panel renders its error path and the spec would be measuring a
    // failure state instead of the inspector.
    const agentStatus = pathname.match(/^\/api\/agents\/([^/]+)\/status$/)
    if (agentStatus) {
      const id = decodeURIComponent(agentStatus[1])
      return json({
        id, name: id, enabled: true, last_run: null,
        budget: { spent: 0, cap: 5, ratio: 0 },
        pending_approvals: 0,
      })
    }
    // --- team hub ---
    if (pathname === '/api/agents/template-status') return json({ agents: [] })
    if (pathname === '/api/agents/unregistered') return json({ profiles: opts.unregistered ?? [] })
    if (pathname === '/api/staff-templates')
      return json({
        templates: opts.staffTemplates ?? [
          {
            role_id: 'qa',
            role: 'Kiểm định',
            domain: 'office',
            reports: [],
            bindings_hint: [],
            persona: '',
            web_search: false,
            recommended_runtime: 'native',
            academic_search: false,
            // A scheduled role, so the gallery's schedule chip is exercised too.
            schedule: { daily: '08:00' },
            has_skills: false,
          },
        ],
      })
    if (pathname === '/api/crews') return json({ crews: [] })
    // No crew manifest ⇒ the banner does not render at all, which is the default here.
    if (pathname === '/api/crew/preview')
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'không có crew manifest' }),
      })

    // --- agent detail tabs ---
    // Every tab reads at least one of these; an unmocked call renders that tab's error
    // path, so the spec would be measuring a failure state instead of the content.
    if (/^\/api\/runs\/[^/]+$/.test(pathname))
      return json({ agent_id: pathname.split('/')[3], runs: [] })
    if (/^\/api\/cost\/[^/]+$/.test(pathname))
      return json({
        agent_id: pathname.split('/')[3],
        series: [],
        cap: 5,
        warn_ratio: 0.8,
        spent_this_month: 0,
      })
    if (/^\/api\/audit\/[^/]+$/.test(pathname))
      return json({ agent_id: pathname.split('/')[3], counts: {}, recent: [] })
    // Memory carries an ?audience query, so this one matches the prefix, not the whole path.
    if (/^\/api\/memory\/[^/]+/.test(pathname))
      return json({ agent_id: pathname.split('/')[3], facts: [], internal_only: false })
    if (/^\/api\/automation\/[^/]+$/.test(pathname))
      return json({ agent_id: pathname.split('/')[3], pending: [] })
    if (pathname === '/api/captures') return json({ captures: opts.captures ?? [] })
    if (/^\/api\/agents\/[^/]+\/config$/.test(pathname))
      return json({
        agent_id: pathname.split('/')[3],
        files: { profile: '', soul: '', project: '', memory: '' },
      })
    if (/^\/api\/agents\/[^/]+\/knowledge\/[^/]+$/.test(pathname))
      return json({ doc: pathname.split('/')[5], raw_mode: true, fields: {}, raw: '' })
    if (/^\/api\/agents\/[^/]+\/skills$/.test(pathname)) return json({ skills: [] })
    // Fleet-level company docs (the system hub's Company tab) — distinct route from the
    // per-agent one below, which lists the docs a single agent has been granted.
    if (pathname === '/api/company-docs') return json({ docs: [] })
    if (/^\/api\/agents\/[^/]+\/company-docs$/.test(pathname)) return json({ docs: [] })
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
      return opts.taskMetrics
        ? json(opts.taskMetrics)
        : route.fulfill({
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
      source_room_id: 't1',
      kind: 'ceo',
      body: { text: 'Soạn báo cáo tuần cho sếp' },
    },
    {
      seq: 2,
      ts: '2026-07-31T09:00:05Z',
      author: 'coordinator',
      source_room_id: 't1',
      kind: 'assignment',
      body: { task_title: 'Soạn báo cáo tuần cho sếp', assigned_to: 'tro-ly-pm', step_count: 3 },
    },
    {
      seq: 3,
      ts: '2026-07-31T09:01:00Z',
      author: 'coordinator',
      source_room_id: 't1',
      kind: 'step_status',
      body: { step_title: 'Thu thập dữ liệu Jira', status: 'started', assigned_to: 'tro-ly-pm' },
    },
    {
      seq: 4,
      ts: '2026-07-31T09:02:00Z',
      author: 'coordinator',
      source_room_id: 't1',
      kind: 'step_status',
      body: { step_title: 'Phân tích số liệu', status: 'started', assigned_to: 'phan-tich-vien' },
    },
  ]
}

/**
 * Deterministic long room timeline — enough rows that the feed overflows its frame at
 * 1440×900 (the internal-scroll assertions need scrollHeight > clientHeight).
 */
/**
 * A workroom's stream.
 *
 * `roomId` stamps `source_room_id` on every event, which the chat thread's reducer uses
 * to decide what belongs to the room it is showing. Defaults to 't1' — the office specs
 * read the overview stream, which shows everything regardless — but a chat spec MUST
 * pass the room it navigates to or the reducer correctly drops every row.
 */
export function makeRoomEvents(count: number, roomId = 't1'): OfficeMessage[] {
  const events: OfficeMessage[] = [
    {
      seq: 1,
      ts: '2026-07-31T09:00:00Z',
      author: 'ceo',
      source_room_id: roomId,
      kind: 'ceo',
      body: { text: 'Soạn báo cáo tuần cho sếp, deadline thứ Sáu' },
    },
    {
      seq: 2,
      ts: '2026-07-31T09:00:05Z',
      author: 'coordinator',
      source_room_id: roomId,
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
        source_room_id: roomId,
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
      source_room_id: roomId,
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
    source_room_id: 't1',
    kind: 'handoff',
    body: {
      step_title: 'Bàn giao báo cáo tuần',
      summary: 'Báo cáo tuần đã xong, đính kèm kết quả.',
      assigned_to: 'tro-ly-pm',
    },
  }
}
