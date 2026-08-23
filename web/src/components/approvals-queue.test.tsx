// The approve/reject scope picker: a bounded once/always/deny dropdown, not free text —
// the value it sends must always be one of the three tokens the ops layer
// (routes_ops_json.py's `_VALID_SCOPES`) accepts. Chịu lực: default is 'once' (today's
// plain-click behavior, no rule learned); picking 'always' only makes sense with
// Approve (Reject disables while 'always' is selected) and vice versa for 'deny'.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import type { FleetApprovalItem, PendingApprovalsIndex } from '../types'
import { ApprovalsQueue } from './approvals-queue'

const APPROVAL: FleetApprovalItem = {
  id: 7,
  reason: 'Đăng bài lên kênh ngoài',
  status: 'pending',
  created_at: '2026-08-19T09:00:00Z',
  action: { type: 'mcp_tool', server: 'slack', tool: 'post_message' },
  agent_id: 'content',
}

function setup(pending: FleetApprovalItem[] = [APPROVAL]) {
  vi.spyOn(api, 'getPendingApprovals').mockResolvedValue({
    pending, count: pending.length,
  } satisfies PendingApprovalsIndex)
  vi.spyOn(api, 'getClarifyPending').mockResolvedValue({ questions: [] })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <ApprovalsQueue />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

test('defaults to once and approve sends scope=once', async () => {
  const approve = vi.spyOn(api, 'approve').mockResolvedValue({ agent_id: 'content', pending: [] })
  setup()
  await screen.findByText('Đăng bài lên kênh ngoài')
  expect(screen.getByRole('combobox').textContent).toContain('Chỉ lần này')
  fireEvent.click(screen.getByRole('button', { name: 'Duyệt' }))
  await waitFor(() => expect(approve).toHaveBeenCalledWith('content', 7, 'once'))
})

test('picking always and approving sends scope=always', async () => {
  const approve = vi.spyOn(api, 'approve').mockResolvedValue({ agent_id: 'content', pending: [] })
  setup()
  await screen.findByText('Đăng bài lên kênh ngoài')
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'always' } })
  fireEvent.click(screen.getByRole('button', { name: 'Duyệt' }))
  await waitFor(() => expect(approve).toHaveBeenCalledWith('content', 7, 'always'))
})

test('picking deny and rejecting sends scope=deny', async () => {
  const reject = vi.spyOn(api, 'reject').mockResolvedValue({ agent_id: 'content', pending: [] })
  setup()
  await screen.findByText('Đăng bài lên kênh ngoài')
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'deny' } })
  fireEvent.click(screen.getByRole('button', { name: 'Từ chối' }))
  await waitFor(() => expect(reject).toHaveBeenCalledWith('content', 7, 'deny'))
})

test('always disables Reject; deny disables Approve — no contradictory scope+decision pair', async () => {
  setup()
  await screen.findByText('Đăng bài lên kênh ngoài')

  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'always' } })
  expect(screen.getByRole('button', { name: 'Duyệt' }).hasAttribute('disabled')).toBe(false)
  expect(screen.getByRole('button', { name: 'Từ chối' }).hasAttribute('disabled')).toBe(true)

  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'deny' } })
  expect(screen.getByRole('button', { name: 'Duyệt' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('button', { name: 'Từ chối' }).hasAttribute('disabled')).toBe(false)

  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'once' } })
  expect(screen.getByRole('button', { name: 'Duyệt' }).hasAttribute('disabled')).toBe(false)
  expect(screen.getByRole('button', { name: 'Từ chối' }).hasAttribute('disabled')).toBe(false)
})
