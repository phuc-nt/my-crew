// S4 ops view tests: config save surfaces the backend validation error. Mocked api (no
// network). Local-only (npm test).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { AgentProvider } from '../agent-context'
import { ApiError, api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { Config } from './Config'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getAgents').mockResolvedValue([
    { id: 'acme', name: 'Acme', enabled: true, last_run: null },
  ])
})

function wrap(ui: React.ReactElement) {
  return render(
    <LanguageProvider>
      <AgentProvider>{ui}</AgentProvider>
    </LanguageProvider>,
  )
}

test('config save surfaces the backend validation error (exact message)', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'name: acme', soul: 's', project: 'p', memory: 'm' },
  })
  vi.spyOn(api, 'saveProfile').mockRejectedValue(
    new ApiError(400, 'profile.yaml must be a YAML mapping'),
  )
  wrap(<Config />)
  await waitFor(() => expect(screen.getByText('profile.yaml')).toBeInTheDocument())
  // the first Save button is profile.yaml's
  fireEvent.click(screen.getAllByText('Lưu')[0])
  await waitFor(() =>
    expect(screen.getByText(/must be a YAML mapping/)).toBeInTheDocument(),
  )
})

test('MEMORY.md editor is read-only (no Save button)', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({
    agent_id: 'acme',
    files: { profile: 'p', soul: 's', project: 'pr', memory: 'agent memory' },
  })
  wrap(<Config />)
  await waitFor(() => expect(screen.getByText(/MEMORY.md \(chỉ đọc\)/)).toBeInTheDocument())
  // profile/soul/project each have a Save → 3 Save buttons, not 4 (memory has none)
  expect(screen.getAllByText('Lưu')).toHaveLength(3)
})
