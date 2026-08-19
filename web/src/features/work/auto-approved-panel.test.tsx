// The live fleet has no auto_approved runs, so this block can only be exercised here.
// Two facts matter: it stays out of the way on a quiet day, and when the trust ladder
// DID act it names the agent — a row that only said "1 report" would be unauditable.
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import { AutoApprovedPanel } from './auto-approved-panel'

vi.mock('../../api/client', () => ({
  api: { getAgents: vi.fn(), getRuns: vi.fn() },
}))

const mocked = vi.mocked(api)
const TODAY = `${new Date().toISOString().slice(0, 10)}T09:15:00Z`

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <AutoApprovedPanel />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocked.getAgents.mockResolvedValue([
    { id: 'secretary' },
    { id: 'researcher' },
  ] as never)
})

describe('AutoApprovedPanel', () => {
  test('renders nothing when no run was auto-delivered today', async () => {
    mocked.getRuns.mockResolvedValue({ runs: [] } as never)
    const { container } = setup()
    await waitFor(() => expect(mocked.getRuns).toHaveBeenCalledTimes(2))
    expect(container.querySelector('.work-auto-approved')).toBeNull()
  })

  test('lists today auto-delivered runs and names the agent', async () => {
    mocked.getRuns.mockImplementation((async (id: string) =>
      id === 'secretary'
        ? { runs: [{ auto_approved: true, ts: TODAY, kind: 'daily' }] }
        : { runs: [] }) as never)
    setup()
    expect(await screen.findByText('secretary')).toBeInTheDocument()
    // The clock reading comes from the run's own timestamp, not from render time.
    expect(screen.getByText(/09:15/)).toBeInTheDocument()
  })

  test('drops runs from an earlier day', async () => {
    mocked.getRuns.mockResolvedValue({
      runs: [{ auto_approved: true, ts: '2020-01-02T09:15:00Z', kind: 'daily' }],
    } as never)
    const { container } = setup()
    await waitFor(() => expect(mocked.getRuns).toHaveBeenCalled())
    await waitFor(() => expect(container.querySelector('.work-auto-approved')).toBeNull())
  })

  test('one unreachable agent does not blank the block', async () => {
    mocked.getRuns.mockImplementation((async (id: string) => {
      if (id === 'researcher') throw new Error('502')
      return { runs: [{ auto_approved: true, ts: TODAY, kind: 'daily' }] }
    }) as never)
    setup()
    expect(await screen.findByText('secretary')).toBeInTheDocument()
  })
})
