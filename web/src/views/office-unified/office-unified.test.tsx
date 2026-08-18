// office-unified.tsx integration test (moved from office-scene.test.tsx in v15 — same
// coverage, new owner): verifies the fallback-trigger wiring (prefers-reduced-motion →
// 2D table instead of Canvas) and that the office SSE stream (mocked, matching
// OfficeRoom.test.tsx's convention — never a real EventSource in tests) is correctly
// reduced into the agent-status-table rows. Canvas itself is NOT exercised here:
// react-three-fiber's Canvas needs a ResizeObserver + WebGL context jsdom doesn't
// provide, so the 3D-render path is only reachable in a browser (E2E); the reducer it
// depends on is covered by agent-office-state.test.ts.
//
// v54 P2: OfficeUnified now renders the action rail (ActionRail) as part of layout A, so
// every render needs PendingApprovalsProvider (the rail reads the shared aggregate) —
// api.getAgents is mocked empty so the fan-out resolves instantly with no items.
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { UiModeProvider } from '../../ui-mode-context'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import * as officeStreamHook from '../../hooks/use-office-stream'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { PendingApprovalsProvider } from '../../pending-approvals-context'
import type { OfficeMessage } from '../../types'
import { OfficeUnified } from './office-unified'

function renderOffice(route = '/office') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <LanguageProvider>
        <UiModeProvider>
          <PendingApprovalsProvider>
            <OfficeUnified />
          </PendingApprovalsProvider>
        </UiModeProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.spyOn(api, 'getAgents').mockResolvedValue([])
  vi.spyOn(api, 'getClarifyPending').mockResolvedValue({ questions: [] })
  vi.spyOn(api, 'getScheduleUpcoming').mockResolvedValue({ items: [] })
})

function mockStream(messages: OfficeMessage[]) {
  vi.spyOn(officeStreamHook, 'useOfficeStream').mockReturnValue({
    messages,
    connected: true,
    errored: false,
  })
}

function stubReducedMotion(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('reduce') ? reduced : false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  }))
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('renders the 2D fallback table (not Canvas) when prefers-reduced-motion is set', () => {
  stubReducedMotion(true)
  mockStream([
    {
      seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'step_status',
      body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
    },
  ])
  renderOffice()
  expect(screen.getAllByText('agent-a').length).toBeGreaterThan(0)
  expect(screen.getByText(DICT.vi['agentStatusTable.stateWorking'])).toBeInTheDocument()
  expect(screen.getAllByText('Demo').length).toBeGreaterThan(0)
  expect(screen.getAllByText('draft').length).toBeGreaterThan(0)
})

test('the fallback table reflects a done state from a handoff event', () => {
  stubReducedMotion(true)
  mockStream([
    {
      seq: 1, ts: 't', author: 'agent-b', source_room_id: 't1', kind: 'handoff',
      body: { task_title: 'Demo', step_title: 'review', message: 'xong', assigned_to: 'agent-b' },
    },
  ])
  renderOffice()
  expect(screen.getAllByText('agent-b').length).toBeGreaterThan(0)
  expect(screen.getByText(DICT.vi['agentStatusTable.stateDone'])).toBeInTheDocument()
})

test('shows an empty-state hint when no agents have appeared in the stream yet', () => {
  stubReducedMotion(true)
  mockStream([])
  renderOffice()
  expect(screen.getAllByText(DICT.vi['agentStatusTable.empty']).length).toBeGreaterThan(0)
})

test('milestone/ceo events alone do not create a desk row in the fallback table', () => {
  stubReducedMotion(true)
  mockStream([
    { seq: 1, ts: 't', author: 'ceo', source_room_id: 't1', kind: 'ceo', body: { text: 'bắt đầu' } },
    { seq: 2, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'milestone', body: { task_title: 'Demo', milestone: 'kickoff' } },
  ])
  renderOffice()
  expect(screen.getAllByText(DICT.vi['agentStatusTable.empty']).length).toBeGreaterThan(0)
})

test('v54 layout A: renders the left action rail alongside the canvas/feed center column', async () => {
  stubReducedMotion(true)
  mockStream([])
  renderOffice()
  // Rail section titles (Chờ anh/chị + Sắp chạy) render regardless of fleet data — the
  // rail is structurally present, not conditionally mounted.
  expect(await screen.findByText(DICT.vi['actionRail.pendingTitle'])).toBeInTheDocument()
  expect(screen.getByText(DICT.vi['actionRail.upcomingTitle'])).toBeInTheDocument()
  // The 2D fallback table (center column) still renders alongside the rail.
  expect(screen.getAllByText(DICT.vi['agentStatusTable.empty']).length).toBeGreaterThan(0)
})

test('v55: right column tabs — Kết quả tab swaps the rooms list for the artifact panel', () => {
  stubReducedMotion(true)
  mockStream([])
  renderOffice()
  // Rooms tab is the default: its search box is present, the artifact hint is not.
  expect(screen.getByPlaceholderText(DICT.vi['workroomList.searchPlaceholder'])).toBeInTheDocument()
  expect(screen.queryByText(DICT.vi['artifactPanel.selectRoomHint'])).toBeNull()
  fireEvent.click(screen.getByText(DICT.vi['officeSide.tabResults']))
  // No room selected → the panel's pick-a-room hint; the rooms search box is gone.
  expect(screen.getByText(DICT.vi['artifactPanel.selectRoomHint'])).toBeInTheDocument()
  expect(screen.queryByPlaceholderText(DICT.vi['workroomList.searchPlaceholder'])).toBeNull()
})

// v56: "live" is the event's own ts vs room-open time (see office-unified.tsx) — these
// tests build history with PAST ts and live deliveries with a FUTURE ts.
const OLD_TS = '2026-07-01T00:00:00Z'
const liveTs = () => new Date(Date.now() + 5_000).toISOString()

function handoffAt(seq: number, ts: string): OfficeMessage {
  return {
    seq, ts, author: 'noi-dung', source_room_id: 't1', kind: 'handoff',
    body: { task_title: 'Demo', step_title: 'soạn', message: 'xong', assigned_to: 'noi-dung' },
  }
}

function rerenderOffice(rerender: ReturnType<typeof renderOffice>['rerender'], route: string) {
  rerender(
    <MemoryRouter initialEntries={[route]}>
      <LanguageProvider>
        <UiModeProvider>
          <PendingApprovalsProvider>
            <OfficeUnified />
          </PendingApprovalsProvider>
        </UiModeProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

test('v55: a live handoff dots the Kết quả tab, but a room\'s replayed history does not', () => {
  stubReducedMotion(true)
  // The real stream replays history ASYNCHRONOUSLY: the room mounts empty, then the old
  // handoffs land. This exact sequence armed a false dot in v56 real-data UAT.
  mockStream([])
  const { rerender } = renderOffice('/office?room=r1')
  const dot = () => document.querySelector('.office-side-badge')
  expect(dot()).toBeNull()
  mockStream([handoffAt(1, OLD_TS), handoffAt(2, OLD_TS)])
  rerenderOffice(rerender, '/office?room=r1')
  expect(dot()).toBeNull() // history replay must NOT arm the dot
  // A NEW handoff arrives on the same room's stream → the tab flags it.
  mockStream([handoffAt(1, OLD_TS), handoffAt(2, OLD_TS), handoffAt(3, liveTs())])
  rerenderOffice(rerender, '/office?room=r1')
  expect(dot()).not.toBeNull()
  // Opening the tab clears it.
  fireEvent.click(screen.getByText(DICT.vi['officeSide.tabResults']))
  expect(dot()).toBeNull()
})

test('v56: toàn cảnh never dots — the results tab there is only a pick-a-room hint', () => {
  stubReducedMotion(true)
  mockStream([])
  const { rerender } = renderOffice('/office')
  const dot = () => document.querySelector('.office-side-badge')
  // Even a genuinely live handoff on the office stream must not arm it.
  mockStream([handoffAt(1, liveTs())])
  rerenderOffice(rerender, '/office')
  expect(dot()).toBeNull()
})

test('v55: the FIRST handoff of a brand-new room dots the tab', () => {
  stubReducedMotion(true)
  const step: OfficeMessage = {
    seq: 1, ts: OLD_TS, author: 'coordinator', source_room_id: 't1', kind: 'step_status',
    body: { task_title: 'Demo', step_title: 'soạn', status: 'started', assigned_to: 'noi-dung' },
  }
  // A room the CEO just created: no handoff yet, only progress events.
  mockStream([step])
  const { rerender } = renderOffice('/office?room=r1')
  const dot = () => document.querySelector('.office-side-badge')
  expect(dot()).toBeNull()
  // Its very first delivery arrives live — v55 live UAT found this swallowed twice.
  mockStream([step, handoffAt(2, liveTs())])
  rerenderOffice(rerender, '/office?room=r1')
  expect(dot()).not.toBeNull()
})

test('v54 P3: clicking a review feed line opens the detail tray in the right column', async () => {
  stubReducedMotion(true)
  mockStream([
    {
      seq: 1, ts: 't', author: 'reviewer', source_room_id: 't1', kind: 'review',
      body: {
        task_title: 'Ra mắt', step_title: 'soát bản nháp', verdict: 'needs_rework',
        failure_count: 1, assigned_to: 'reviewer',
      },
    },
  ])
  renderOffice()
  fireEvent.click(screen.getByText(/Ra mắt \/ soát bản nháp: cần sửa/))
  expect(await screen.findByText(DICT.vi['reviewDetailTray.title'])).toBeInTheDocument()
  expect(screen.getByText(DICT.vi['reviewDetailTray.unavailable'])).toBeInTheDocument()
})
