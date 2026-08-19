// office-page.tsx integration test. Ported from the old office-unified.test.tsx: the
// screen was rebuilt around use-office-orchestration, but the guarantees it made about
// the DESK FLOOR are the same ones the CEO relies on, so they are re-asserted against
// the new page rather than retired with the old file.
//
// Canvas itself is NOT exercised here: react-three-fiber's Canvas needs a ResizeObserver
// and a WebGL context jsdom does not provide, so the 3D path is reachable only in a real
// browser (e2e). Every test below forces the 2D fallback, which renders the SAME derived
// desk map — the reducer behind it is covered by office-3d/agent-office-state.test.ts.
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import * as officeStreamHook from '../../hooks/use-office-stream'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { PendingApprovalsProvider } from '../../pending-approvals-context'
import { UiModeProvider } from '../../ui-mode-context'
import type { OfficeMessage } from '../../types'
import { OfficePage } from './office-page'

function renderOffice(route = '/office') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <LanguageProvider>
        <UiModeProvider>
          <PendingApprovalsProvider>
            <OfficePage />
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
    messages, connected: true, errored: false,
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
  expect(screen.getByText(DICT.vi['agentStatusTable.stateDone'])).toBeInTheDocument()
})

test('milestone/ceo events alone do not create a desk row', () => {
  stubReducedMotion(true)
  mockStream([
    { seq: 1, ts: 't', author: 'ceo', source_room_id: 't1', kind: 'ceo', body: { text: 'bắt đầu' } },
    {
      seq: 2, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'milestone',
      body: { task_title: 'Demo', milestone: 'kickoff' },
    },
  ])
  renderOffice()
  expect(screen.getAllByText(DICT.vi['agentStatusTable.empty']).length).toBeGreaterThan(0)
})

test('clicking a desk opens the inspector — in low mode too, since /office is the deck', () => {
  stubReducedMotion(true)
  vi.spyOn(api, 'getAgentStatus').mockResolvedValue({
    id: 'agent-a', trust_mode: 'guarded', budget: { spent: 0, cap: 10 },
  } as never)
  mockStream([
    {
      seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'step_status',
      body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
    },
  ])
  renderOffice()
  // The old screen navigated away on a low-mode desk click; the hub inspects in place.
  fireEvent.click(screen.getAllByText('agent-a')[0])
  expect(screen.getByLabelText(DICT.vi['deskInspector.ariaLabel'].replace('{agentId}', 'agent-a')))
    .toBeInTheDocument()
})

test('the inspector shows the live tool call while a step_activity is the desk\'s latest', () => {
  stubReducedMotion(true)
  vi.spyOn(api, 'getAgentStatus').mockResolvedValue({
    id: 'agent-a', trust_mode: 'guarded', budget: { spent: 0, cap: 10 },
  } as never)
  mockStream([
    {
      seq: 1, ts: 't', author: 'coordinator', source_room_id: 't1', kind: 'step_status',
      body: { task_title: 'Demo', step_title: 'draft', status: 'started', assigned_to: 'agent-a' },
    },
    {
      seq: 2, ts: 't', author: 'agent-a', source_room_id: 't1', kind: 'step_activity',
      body: { agent: 'agent-a', tool: 'web_search', count: 2, phase: 'calling-tool' },
    },
  ])
  renderOffice()
  fireEvent.click(screen.getAllByText('agent-a')[0])
  expect(screen.getByTestId('desk-activity').textContent).toContain('web_search')
})

test('quick assign opens the chat hub composer in a dialog rather than a second one', async () => {
  stubReducedMotion(true)
  mockStream([])
  renderOffice()
  fireEvent.click(screen.getByTestId('office-quick-assign'))
  const dialog = await screen.findByTestId('quick-assign-modal')
  // The composer's own brief field, matched by its placeholder — proof this is the chat
  // hub's AssignComposer and not a lookalike input the office grew on its own.
  expect(dialog.querySelector(
    `input[placeholder="${DICT.vi['assignComposer.placeholderNew']}"]`,
  )).not.toBeNull()
})
