// v53 primitives: class mapping, native-prop passthrough, formatCost rule.
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { formatCost } from '../../labels'
import { Badge } from './badge'
import { Button } from './button'
import { Card } from './card'
import { EmptyState } from './empty-state'
import { Input } from './input'
import { PageHeader } from './page-header'

test('Button maps variants to the canonical classes and defaults to type=button', () => {
  render(
    <>
      <Button>G</Button>
      <Button variant="primary">P</Button>
      <Button variant="danger">D</Button>
      <Button variant="chip">C</Button>
    </>,
  )
  expect(screen.getByText('G').className).toBe('btn')
  expect(screen.getByText('P').className).toBe('btn btn-primary')
  expect(screen.getByText('D').className).toBe('btn btn-danger')
  expect(screen.getByText('C').className).toBe('chip')
  expect((screen.getByText('G') as HTMLButtonElement).type).toBe('button')
})

test('Button passes through onClick/disabled and extra className', () => {
  const onClick = vi.fn()
  render(
    <>
      <Button onClick={onClick} className="extra">Go</Button>
      <Button disabled>Off</Button>
    </>,
  )
  fireEvent.click(screen.getByText('Go'))
  expect(onClick).toHaveBeenCalledOnce()
  expect(screen.getByText('Go').className).toBe('btn extra')
  expect((screen.getByText('Off') as HTMLButtonElement).disabled).toBe(true)
})

test('Badge is always pill (.badge) with a tone class', () => {
  render(<Badge tone="danger">2 lỗi</Badge>)
  expect(screen.getByText('2 lỗi').className).toBe('badge badge-danger')
})

test('Card/Input/EmptyState render their canonical classes', () => {
  render(
    <>
      <Card data-testid="c">x</Card>
      <Input placeholder="nhập…" />
      <EmptyState>Chưa có gì.</EmptyState>
    </>,
  )
  expect(screen.getByTestId('c').className).toBe('card')
  expect(screen.getByPlaceholderText('nhập…').className).toBe('ui-input')
  expect(screen.getByText('Chưa có gì.').className).toBe('ops-chat-empty')
})

test('PageHeader renders h2 + actions row', () => {
  render(<PageHeader title="Đội" actions={<Button>Thêm</Button>} />)
  expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Đội')
  expect(screen.getByText('Thêm').closest('.page-header-actions')).toBeTruthy()
})

test('formatCost: 4 decimals under $1, 2 from $1, dash for null/NaN', () => {
  expect(formatCost(0.00336)).toBe('$0.0034')
  expect(formatCost(0.9999)).toBe('$0.9999')
  expect(formatCost(1)).toBe('$1.00')
  expect(formatCost(2.7)).toBe('$2.70')
  expect(formatCost(450)).toBe('$450.00')
  expect(formatCost(null)).toBe('—')
  expect(formatCost(Number.NaN)).toBe('—')
})
