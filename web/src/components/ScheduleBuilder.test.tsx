import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { buildCron, ScheduleBuilder } from './ScheduleBuilder'

test('buildCron returns null when no days selected', () => {
  expect(buildCron('09:00', [])).toBeNull()
})

test('buildCron builds a 5-field cron string sorted by day', () => {
  expect(buildCron('09:30', [5, 1, 3])).toBe('30 9 * * 1,3,5')
})

test('ScheduleBuilder selecting a day calls onChange with the generated cron', () => {
  const onChange = vi.fn()
  render(<ScheduleBuilder kind="daily" onChange={onChange} />)
  fireEvent.click(screen.getByLabelText('Mon'))
  expect(onChange).toHaveBeenCalledWith('0 9 * * 1')
  expect(screen.getByText(/cron: 0 9 \* \* 1/)).toBeInTheDocument()
})

test('ScheduleBuilder with no days shows manual-only text', () => {
  render(<ScheduleBuilder kind="daily" onChange={vi.fn()} />)
  expect(screen.getByText(/manual only/)).toBeInTheDocument()
})
