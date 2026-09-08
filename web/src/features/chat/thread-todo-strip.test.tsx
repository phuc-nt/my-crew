// The todo strip under a thread: progress arithmetic, the per-status marks, and that
// the strip renders from the room's artifact index (and not at all on the overview).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import type { RoomArtifactStep } from '../../types'
import { ThreadTodoStrip, doneCount, stepMark } from './thread-todo-strip'

function step(id: string, status: string): RoomArtifactStep {
  return { step_id: id, title: `bước ${id}`, assigned_to: 'content', status, seq: 1, step_type: 'content' }
}

function strip(roomId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <ThreadTodoStrip roomId={roomId} />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.restoreAllMocks())

describe('doneCount / stepMark', () => {
  it('counts only finished steps and marks each status distinctly', () => {
    expect(doneCount([step('a', 'done'), step('b', 'running'), step('c', 'skipped')])).toBe(1)
    expect(stepMark('done')).toBe('✓')
    expect(stepMark('running')).toBe('▶')
    expect(stepMark('failed')).toBe('✕')
    expect(stepMark('awaiting_approval')).toBe('⏸')
    expect(stepMark('skipped')).toBe('–')
    expect(stepMark('open')).toBe('○')
  })
})

describe('ThreadTodoStrip', () => {
  it('never queries on the overview room', () => {
    const spy = vi.spyOn(api, 'getRoomArtifacts')
    strip('office')
    expect(spy).not.toHaveBeenCalled()
    expect(screen.queryByTestId('thread-todo-strip')).toBeNull()
  })

  it('renders each task with its done/total and collapses on click', async () => {
    vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue({
      tasks: [{
        task_id: 't1', title: 'Viết bài blog', pic_id: 'content', status: 'in_progress',
        steps: [step('s1', 'done'), step('s2', 'running'), step('s3', 'open')],
      }],
    })
    strip('room-1')
    await waitFor(() => expect(screen.getByTestId('thread-todo-strip')).toBeInTheDocument())
    expect(screen.getByTestId('todo-progress').textContent).toBe('1/3 bước')
    expect(document.querySelectorAll('.todo-step').length).toBe(3)
    expect(document.querySelector('.todo-step.is-running .todo-step-mark')?.textContent).toBe('▶')
    fireEvent.click(screen.getByRole('button', { expanded: true }))
    expect(document.querySelectorAll('.todo-step').length).toBe(0)
  })

  it('stays hidden when the room has no task', async () => {
    const spy = vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue({ tasks: [] })
    strip('room-2')
    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(screen.queryByTestId('thread-todo-strip')).toBeNull()
  })
})
