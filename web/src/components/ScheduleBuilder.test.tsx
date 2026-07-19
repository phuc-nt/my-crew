import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { LanguageProvider } from '../i18n/language-context'
import { buildCron, ScheduleBuilder } from './ScheduleBuilder'

function renderBuilder(props: Parameters<typeof ScheduleBuilder>[0]) {
  return render(
    <LanguageProvider>
      <ScheduleBuilder {...props} />
    </LanguageProvider>,
  )
}

test('buildCron returns null when no days selected', () => {
  expect(buildCron('09:00', [])).toBeNull()
})

test('buildCron builds a 5-field cron string sorted by day', () => {
  expect(buildCron('09:30', [5, 1, 3])).toBe('30 9 * * 1,3,5')
})

test('ScheduleBuilder selecting a day calls onChange with the generated cron', () => {
  const onChange = vi.fn()
  renderBuilder({ kind: 'daily', onChange })
  fireEvent.click(screen.getByLabelText('T2'))
  expect(onChange).toHaveBeenCalledWith('0 9 * * 1')
  expect(screen.getByText(/cron: 0 9 \* \* 1/)).toBeInTheDocument()
})

test('ScheduleBuilder with no days shows manual-only text', () => {
  renderBuilder({ kind: 'daily', onChange: vi.fn() })
  expect(screen.getByText(/chỉ chạy thủ công/)).toBeInTheDocument()
})
