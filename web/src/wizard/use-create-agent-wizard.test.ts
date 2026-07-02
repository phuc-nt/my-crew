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
