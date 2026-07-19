// v54 P3 → P4b: review detail tray — data-source verification at cook time found the
// review event body has no task_id/step_id/attempt_id (no-content-echo posture), so this
// tray correlates by reviewer (`assigned_to`, an exact join to `captures.agent_id`) +
// reproducing the event's own criteria_total/criteria_passed/verdict against each
// candidate capture's stored criteria. An unambiguous match renders criterion rows; zero
// or multiple matches (or a pre-P4b event/row) fall back to the EmptyState.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import type { CaptureDetail, CaptureRow, OfficeMessage } from '../../types'
import { ReviewDetailTray } from './review-detail-tray'

afterEach(() => vi.restoreAllMocks())

function reviewMessage(body: OfficeMessage['body'], seq = 1): OfficeMessage {
  return { seq, ts: 't', author: 'reviewer', kind: 'review', body }
}

const ROW: CaptureRow = {
  attempt_id: 'r1', task_id: 't1', step_id: 's1-review-0-0', agent_id: 'reviewer',
  engine: 'native', status: 'done', step_type: 'review', review_round: 0,
  cost_usd: 0.01, cost_source: 'exact', input_tokens: 10, output_tokens: 5,
  started_at: 's', ended_at: 'e', duration_ms: 100, error: '', ts: '2026-07-19T00:00:00Z',
}

// `api.getCaptureDetail`'s declared return type (`Promise<CaptureRow>`, in client.ts —
// out of this phase's file ownership) predates P4b's `criteria` field; the real wire
// payload carries it (see routes_observability.py's `capture_detail`). Same narrow cast
// the tray component itself uses at its call site.
function detailOf(criteria: CaptureDetail['criteria']): CaptureDetail {
  return { ...ROW, criteria }
}

test('renders criterion rows from the resolved capture detail', async () => {
  vi.spyOn(api, 'getCaptures').mockResolvedValue({ captures: [ROW] })
  vi.spyOn(api, 'getCaptureDetail').mockResolvedValue(detailOf([
    { criterion: 'handles empty input', passed: true, note: '' },
    { criterion: 'returns typed errors', passed: false, note: 'missing validation' },
  ]))

  render(
    <LanguageProvider>
      <ReviewDetailTray
        message={reviewMessage({
          task_title: 'Ra mắt', step_title: 'soát bản nháp', verdict: 'needs_rework',
          failure_count: 1, criteria_total: 2, criteria_passed: 1, assigned_to: 'reviewer',
        })}
        onClose={() => {}}
      />
    </LanguageProvider>,
  )

  await waitFor(() => expect(screen.getByText('handles empty input')).toBeTruthy())
  expect(screen.getByText('returns typed errors')).toBeTruthy()
  expect(screen.getByText('missing validation')).toBeTruthy()
})

test('falls back to the empty state when no candidate matches the event counts', async () => {
  vi.spyOn(api, 'getCaptures').mockResolvedValue({ captures: [ROW] })
  vi.spyOn(api, 'getCaptureDetail').mockResolvedValue(
    detailOf([{ criterion: 'x', passed: true, note: '' }]),
  )

  render(
    <LanguageProvider>
      <ReviewDetailTray
        message={reviewMessage({
          task_title: 'Ra mắt', step_title: 'soát bản nháp', verdict: 'needs_rework',
          failure_count: 2, criteria_total: 5, criteria_passed: 3, assigned_to: 'reviewer',
        })}
        onClose={() => {}}
      />
    </LanguageProvider>,
  )

  await waitFor(() => expect(screen.getByText(/Chưa có chi tiết từng tiêu chí/)).toBeTruthy())
})

test('falls back to the empty state when the event predates per-criterion counts', async () => {
  const spy = vi.spyOn(api, 'getCaptures')
  render(
    <LanguageProvider>
      <ReviewDetailTray
        message={reviewMessage({ task_title: 'Ra mắt', step_title: 'soát bản nháp', verdict: 'passed' })}
        onClose={() => {}}
      />
    </LanguageProvider>,
  )
  expect(screen.getByText(/Ra mắt \/ soát bản nháp: đạt/)).toBeTruthy()
  await waitFor(() => expect(screen.getByText(/Chưa có chi tiết từng tiêu chí/)).toBeTruthy())
  expect(spy).not.toHaveBeenCalled() // no assigned_to/criteria_total → never even asks the API
})

test('close button invokes onClose', async () => {
  vi.spyOn(api, 'getCaptures').mockResolvedValue({ captures: [] })
  const onClose = vi.fn()
  render(
    <LanguageProvider>
      <ReviewDetailTray
        message={reviewMessage({ task_title: 'T', step_title: 'S', verdict: 'passed' })}
        onClose={onClose}
      />
    </LanguageProvider>,
  )
  fireEvent.click(screen.getByText('Đóng'))
  expect(onClose).toHaveBeenCalled()
})
