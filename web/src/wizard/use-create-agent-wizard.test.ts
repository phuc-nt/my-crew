// Wizard state machine: pack-switch must reset reports/schedule/bindings (a stale report
// kind or server binding from the old pack can 400 on Create with no obvious cause), and
// ID_PATTERN must mirror the backend's agent-id rule exactly.
import { act, renderHook } from '@testing-library/react'
import { expect, test } from 'vitest'
import { ID_PATTERN, useCreateAgentWizard } from './use-create-agent-wizard'

const PM_PACK = { id: 'pm', name: 'Project Management', report_kinds: ['daily'], servers: ['jira'] }
const HR_PACK = { id: 'hr', name: 'Human Resources', report_kinds: ['headcount'], servers: ['slack'] }

test('ID_PATTERN mirrors the backend agent-id rule (no leading -, _ allowed)', () => {
  expect(ID_PATTERN.test('acme-pm')).toBe(true)
  expect(ID_PATTERN.test('acme_pm')).toBe(true)
  expect(ID_PATTERN.test('a1')).toBe(true)
  expect(ID_PATTERN.test('-acme')).toBe(false)
  expect(ID_PATTERN.test('_acme')).toBe(false)
  expect(ID_PATTERN.test('Acme')).toBe(false)
})

test('selectPack resets reports/schedule/bindings but keeps id/name/persona', () => {
  const { result } = renderHook(() => useCreateAgentWizard())

  act(() => result.current.selectPack(PM_PACK))
  act(() => result.current.update('id', 'acme-pm'))
  act(() => result.current.update('name', 'Acme PM'))
  act(() => result.current.update('persona', 'hand-written soul'))
  act(() => result.current.toggleReport('daily'))
  act(() => result.current.setCronFor('daily', '0 9 * * 1'))
  act(() => result.current.update('jiraProjectKey', 'ACME'))

  expect(result.current.state.reports).toEqual(['daily'])
  expect(result.current.state.schedule).toEqual({ daily: '0 9 * * 1' })
  expect(result.current.state.jiraProjectKey).toBe('ACME')

  // switching packs — the M1 bug: stale reports/schedule/bindings must NOT survive
  act(() => result.current.selectPack(HR_PACK))

  expect(result.current.state.pack).toEqual(HR_PACK)
  expect(result.current.state.reports).toEqual([])
  expect(result.current.state.schedule).toEqual({})
  expect(result.current.state.jiraProjectKey).toBe('')
  expect(result.current.state.slackReportChannel).toBe('')
  // pack-independent fields survive the switch
  expect(result.current.state.id).toBe('acme-pm')
  expect(result.current.state.name).toBe('Acme PM')
  expect(result.current.state.persona).toBe('hand-written soul')
})

test('buildSpec never sends a report kind that is not in the currently selected pack', () => {
  const { result } = renderHook(() => useCreateAgentWizard())
  act(() => result.current.selectPack(PM_PACK))
  act(() => result.current.toggleReport('daily'))
  act(() => result.current.selectPack(HR_PACK)) // pm's "daily" must not leak into hr's spec

  const spec = result.current.buildSpec()
  expect(spec.domain).toBe('hr')
  expect(spec.reports).toEqual([])
})

// Template prefill (staff-template-picker → applyTemplate).
const PM_TEMPLATE = {
  role_id: 'pm-coordinator',
  role: 'Điều phối dự án',
  domain: 'pm',
  reports: ['daily'],
  bindings_hint: ['jira', 'slack'],
  persona: '# SOUL\n\nBạn là Điều phối dự án.',
  web_search: false,
  recommended_runtime: 'native',
}

test('applyTemplate carries the web_search opt-in into buildSpec', () => {
  const { result } = renderHook(() => useCreateAgentWizard())
  const research = { ...PM_TEMPLATE, role_id: 'nghien-cuu', web_search: true }
  act(() => result.current.applyTemplate(research, PM_PACK))

  expect(result.current.state.webSearch).toBe(true)
  expect(result.current.buildSpec().web_search).toBe(true)

  // A non-research template resets it — the flag never leaks across templates.
  act(() => result.current.applyTemplate(PM_TEMPLATE, PM_PACK))
  expect(result.current.state.webSearch).toBe(false)
  expect(result.current.buildSpec().web_search).toBeUndefined()
})

test('applyTemplate prefills recommended_runtime and buildSpec forwards non-native', () => {
  const { result } = renderHook(() => useCreateAgentWizard())
  const deep = { ...PM_TEMPLATE, role_id: 'nghien-cuu', recommended_runtime: 'deep_agent' }
  act(() => result.current.applyTemplate(deep, PM_PACK))

  expect(result.current.state.agentRuntime).toBe('deep_agent')
  // deep_agent is emitted as a mapping carrying its required sandbox block (a bare string would
  // be DOA — the backend fails closed with no sandbox).
  expect(result.current.buildSpec().agent_runtime).toEqual({
    kind: 'deep_agent',
    sandbox: { provider: 'docker' },
  })

  // A native template omits agent_runtime from the spec (default).
  act(() => result.current.applyTemplate({ ...PM_TEMPLATE, recommended_runtime: 'native' }, PM_PACK))
  expect(result.current.state.agentRuntime).toBe('native')
  expect(result.current.buildSpec().agent_runtime).toBeUndefined()
})

test('applyTemplate prefills pack/role/persona/reports and locks persona from auto-regen', () => {
  const { result } = renderHook(() => useCreateAgentWizard())
  act(() => result.current.applyTemplate(PM_TEMPLATE, PM_PACK))

  expect(result.current.state.pack).toEqual(PM_PACK)
  expect(result.current.state.role).toBe('Điều phối dự án')
  expect(result.current.state.persona).toBe(PM_TEMPLATE.persona)
  expect(result.current.state.personaEdited).toBe(true)
  expect(result.current.state.reports).toEqual(['daily'])

  const spec = result.current.buildSpec()
  expect(spec.domain).toBe('pm')
  expect(spec.reports).toEqual(['daily'])
  expect(spec.persona).toBe(PM_TEMPLATE.persona)
})

test('applyTemplate drops report kinds the resolved pack does not actually serve', () => {
  const { result } = renderHook(() => useCreateAgentWizard())
  const staleTemplate = { ...PM_TEMPLATE, reports: ['daily', 'ghost-kind'] }
  act(() => result.current.applyTemplate(staleTemplate, PM_PACK))

  expect(result.current.state.reports).toEqual(['daily'])
})

test('buildSpec forwards an explicit trust_mode and omits the inherit default', () => {
  const { result } = renderHook(() => useCreateAgentWizard())
  act(() => result.current.applyTemplate(PM_TEMPLATE, PM_PACK))

  // '' = inherit the company default → the key must be absent from the POST body.
  expect(result.current.buildSpec().trust_mode).toBeUndefined()

  act(() => result.current.update('trustMode', 'guarded'))
  expect(result.current.buildSpec().trust_mode).toBe('guarded')

  act(() => result.current.update('trustMode', 'autonomous'))
  expect(result.current.buildSpec().trust_mode).toBe('autonomous')
})
