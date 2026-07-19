// Dual-lens P2: header mode toggle + high-mode office panels (health strip, desk
// inspector). jsdom covers logic/gating only — visuals are the phase-4 browser UAT.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { UiModeProvider, useUiMode } from '../../ui-mode-context'
import { DeskInspector } from './desk-inspector'
import { OfficeHealthStrip } from './office-health-strip'

afterEach(() => {
  vi.restoreAllMocks()
})

function ModeProbe() {
  const { isHigh, setMode } = useUiMode()
  return (
    <button type="button" onClick={() => setMode(isHigh ? 'low' : 'high')}>
      {isHigh ? 'high-on' : 'low-on'}
    </button>
  )
}

// Persistence is the context's own concern — this jsdom setup has no localStorage.
test('mode toggle flips low-high-low through the shared context', () => {
  render(<UiModeProvider><ModeProbe /></UiModeProvider>)
  fireEvent.click(screen.getByText('low-on'))
  expect(screen.getByText('high-on')).toBeTruthy()
  fireEvent.click(screen.getByText('high-on'))
  expect(screen.getByText('low-on')).toBeTruthy()
})

test('health strip: alive beat + failing checks render as chips with hints', async () => {
  vi.spyOn(api, 'getCoordinatorHealth').mockResolvedValue({
    alive: true, last_beat_ago_s: 12.4, reason: '',
  })
  vi.spyOn(api, 'getIntegrationHealth').mockResolvedValue({
    checked_at: 1,
    checks: [
      { id: 'a', label: 'OpenRouter', ok: true, detail: 'k ✓', hint: '' },
      { id: 'b', label: 'Email (SMTP)', ok: false, detail: 'chưa cấu hình', hint: 'điền SMTP' },
    ],
  })
  render(<LanguageProvider><OfficeHealthStrip /></LanguageProvider>)
  await waitFor(() =>
    expect(
      screen.getByText(DICT.vi['officeHealthStrip.coordinatorAlive'].replace('{seconds}', '12')),
    ).toBeTruthy(),
  )
  expect(screen.getByText('✓ 1')).toBeTruthy()
  const bad = screen.getByText('✗ Email (SMTP)')
  expect(bad.getAttribute('title')).toContain('điền SMTP')
})

test('desk inspector: fetches status always, task cost only when the desk is PIC', async () => {
  const statusSpy = vi.spyOn(api, 'getAgentStatus').mockResolvedValue({
    id: 'hr', name: 'HR', enabled: true, last_run: null,
    budget: { spent: 1.23, cap: 50, ratio: 0.02 }, pending_approvals: 0,
    trust_mode: 'autonomous',
  })
  const costSpy = vi.spyOn(api, 'getTeamTaskCost').mockResolvedValue({
    task_id: 't9', total_cost_usd: 0.4567, total_input_tokens: 100, total_output_tokens: 50,
    steps: [{ engine: 'deep_agent', cost_usd: 0.4, step_id: 's1' }],
  })
  const desk = {
    id: 'hr', state: 'working' as const, taskTitle: 'Demo', stepTitle: 'draft',
    phase: null, attemptId: null, consultWith: null, lastVerdict: null,
    picTasks: new Set(['t9']),
  }
  render(
    <MemoryRouter>
      <LanguageProvider>
        <DeskInspector agentId="hr" desk={desk} onClose={() => {}} />
      </LanguageProvider>
    </MemoryRouter>,
  )
  await waitFor(() =>
    expect(screen.getByText(new RegExp(DICT.vi['deskInspector.monthlyBudget']))).toBeTruthy(),
  )
  expect(statusSpy).toHaveBeenCalledWith('hr')
  expect(costSpy).toHaveBeenCalledWith('t9')
  await waitFor(() => expect(screen.getByText(/\$0\.4567/)).toBeTruthy())
  expect(screen.getByText(/deep_agent/)).toBeTruthy()
})

test('desk inspector without a PIC task never calls the cost endpoint', async () => {
  vi.spyOn(api, 'getAgentStatus').mockResolvedValue({
    id: 'hr', name: 'HR', enabled: true, last_run: null,
    budget: { spent: 0, cap: 50, ratio: 0 }, pending_approvals: 0,
  })
  const costSpy = vi.spyOn(api, 'getTeamTaskCost')
  const desk = {
    id: 'hr', state: 'idle' as const, taskTitle: null, stepTitle: null,
    phase: null, attemptId: null, consultWith: null, lastVerdict: null,
    picTasks: new Set<string>(),
  }
  render(
    <MemoryRouter>
      <LanguageProvider>
        <DeskInspector agentId="hr" desk={desk} onClose={() => {}} />
      </LanguageProvider>
    </MemoryRouter>,
  )
  await waitFor(() =>
    expect(screen.getByText(new RegExp(DICT.vi['deskInspector.monthlyBudget']))).toBeTruthy(),
  )
  expect(costSpy).not.toHaveBeenCalled()
})
