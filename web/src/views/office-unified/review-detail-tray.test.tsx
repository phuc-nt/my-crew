// v54 P3: review detail tray — data-source verification at cook time found the review
// step's per-criterion detail (criterion text + note) is NOT persisted anywhere a read
// API can return (see review-detail-tray.tsx's module docstring); this tray therefore
// always shows the summary + an EmptyState, never invented per-criterion rows.
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { LanguageProvider } from '../../i18n/language-context'
import type { OfficeMessage } from '../../types'
import { ReviewDetailTray } from './review-detail-tray'

function reviewMessage(body: OfficeMessage['body']): OfficeMessage {
  return { seq: 1, ts: 't', author: 'reviewer', kind: 'review', body }
}

test('renders the review summary and the criteria-unavailable empty state', () => {
  render(
    <LanguageProvider>
      <ReviewDetailTray
        message={reviewMessage({
          task_title: 'Ra mắt', step_title: 'soát bản nháp', verdict: 'needs_rework',
          failure_count: 2, criteria_total: 5, criteria_passed: 3,
        })}
        onClose={() => {}}
      />
    </LanguageProvider>,
  )
  expect(screen.getByText(/Ra mắt \/ soát bản nháp: cần sửa \(2 lỗi\)/)).toBeTruthy()
  expect(screen.getByText(/Chưa có chi tiết từng tiêu chí/)).toBeTruthy()
})

test('close button invokes onClose', () => {
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
