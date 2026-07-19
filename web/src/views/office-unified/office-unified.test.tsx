// office-unified.tsx integration test (moved from office-scene.test.tsx in v15 — same
// coverage, new owner): verifies the fallback-trigger wiring (prefers-reduced-motion →
// 2D table instead of Canvas) and that the office SSE stream (mocked, matching
// OfficeRoom.test.tsx's convention — never a real EventSource in tests) is correctly
// reduced into the agent-status-table rows. Canvas itself is NOT exercised here:
// react-three-fiber's Canvas needs a ResizeObserver + WebGL context jsdom doesn't
// provide, so the 3D-render path is only reachable in a browser (E2E); the reducer it
// depends on is covered by agent-office-state.test.ts.
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { UiModeProvider } from '../../ui-mode-context'
import { afterEach, expect, test, vi } from 'vitest'
import * as officeStreamHook from '../../hooks/use-office-stream'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import type { OfficeMessage } from '../../types'
import { OfficeUnified } from './office-unified'

function renderOffice() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <UiModeProvider>
          <OfficeUnified />
        </UiModeProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

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
      seq: 1, ts: 't', author: 'coordinator', kind: 'step_status',
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
      seq: 1, ts: 't', author: 'agent-b', kind: 'handoff',
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
    { seq: 1, ts: 't', author: 'ceo', kind: 'ceo', body: { text: 'bắt đầu' } },
    { seq: 2, ts: 't', author: 'coordinator', kind: 'milestone', body: { task_title: 'Demo', milestone: 'kickoff' } },
  ])
  renderOffice()
  expect(screen.getAllByText(DICT.vi['agentStatusTable.empty']).length).toBeGreaterThan(0)
})
