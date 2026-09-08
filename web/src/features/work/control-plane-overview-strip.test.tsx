import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import type { ControlPlaneOverviewPayload } from '../../types'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { ControlPlaneOverviewStrip } from './control-plane-overview-strip'

const OVERVIEW: ControlPlaneOverviewPayload = {
  v: 1,
  registry: { agents: [] },
  health: { coordinator_ok: true, integrations: [] },
  queue: { depth: 4, running: 2, stalled: 0 },
  approvals: { pending_total: 3, pending_by_agent: { 'ke-toan': 2, 'tro-ly-pm': 1 } },
}

function renderStrip() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider>
        <ControlPlaneOverviewStrip />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('ControlPlaneOverviewStrip', () => {
  it('renders the four counters and the coordinator badge from the overview payload', async () => {
    vi.spyOn(api, 'getControlPlaneOverview').mockResolvedValue(OVERVIEW)
    renderStrip()
    const strip = await screen.findByTestId('control-plane-strip')
    const tiles = strip.querySelectorAll('.stat-tile')
    expect(tiles).toHaveLength(4)
    expect(tiles[0].textContent).toContain(DICT.vi['controlPlane.queueDepth'])
    expect(tiles[0].querySelector('.stat-tile-value')?.textContent).toBe('4')
    expect(tiles[1].querySelector('.stat-tile-value')?.textContent).toBe('2')
    expect(tiles[2].querySelector('.stat-tile-value')?.textContent).toBe('0')
    expect(tiles[2].classList.contains('stat-tile-warn')).toBe(false)
    expect(tiles[3].querySelector('.stat-tile-value')?.textContent).toBe('3')
    expect(tiles[3].querySelector('.stat-tile-footer')?.textContent).toBe('ke-toan ×2 · tro-ly-pm ×1')
    expect(strip.querySelector('.control-plane-coordinator')?.textContent).toBe(
      DICT.vi['controlPlane.coordinatorOk'],
    )
    expect(strip.querySelector('.control-plane-coordinator')?.className).toContain('badge-ok')
  })

  it('flags stalled work and a silent coordinator', async () => {
    vi.spyOn(api, 'getControlPlaneOverview').mockResolvedValue({
      ...OVERVIEW,
      health: { coordinator_ok: false, integrations: [] },
      queue: { depth: 1, running: 0, stalled: 1 },
      approvals: { pending_total: 0, pending_by_agent: {} },
    })
    renderStrip()
    const strip = await screen.findByTestId('control-plane-strip')
    const stalled = strip.querySelectorAll('.stat-tile')[2]
    expect(stalled.classList.contains('stat-tile-warn')).toBe(true)
    expect(stalled.querySelector('.badge-warn')).not.toBeNull()
    expect(strip.querySelector('.control-plane-coordinator')?.className).toContain('badge-danger')
    expect(strip.textContent).toContain(DICT.vi['controlPlane.coordinatorDown'])
    // No per-agent footer when nobody is waiting.
    expect(strip.querySelectorAll('.stat-tile')[3].querySelector('.stat-tile-footer')).toBeNull()
  })

  it('degrades to one muted line when the overview cannot be read', async () => {
    vi.spyOn(api, 'getControlPlaneOverview').mockRejectedValue(new Error('boom'))
    renderStrip()
    const strip = await screen.findByTestId('control-plane-strip')
    expect(strip.textContent).toBe(DICT.vi['controlPlane.loadFailed'])
    expect(strip.querySelector('.stat-tile')).toBeNull()
  })
})
