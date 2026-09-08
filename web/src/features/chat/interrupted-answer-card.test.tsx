// The "câu trả lời dở" card: which steps qualify, what of the dead attempt is shown, and
// that the retry button dispatches the same request the todo strip's retry would.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import type { RoomArtifactTask, StepArtifactPayload } from '../../types'
import {
  InterruptedAnswers,
  PARTIAL_PREVIEW_CHARS,
  interruptedSteps,
  partialPreview,
} from './interrupted-answer-card'

function task(status: string, steps: Array<[string, string, number]>): RoomArtifactTask {
  return {
    task_id: 't1',
    title: 'Báo cáo tuần',
    pic_id: 'tro-ly-pm',
    status,
    steps: steps.map(([id, st, seq]) => ({
      step_id: id, title: `bước ${id}`, assigned_to: 'content', status: st, seq, step_type: 'content',
    })),
  }
}

function artifact(over: Partial<StepArtifactPayload> = {}): StepArtifactPayload {
  return {
    task_id: 't1', step_title: 'bước s2', attempt: 'a1', self_check_failed: false,
    result_text: 'Nháp: giá tăng theo https://vnexpress.net/a và https://cafef.vn/b',
    status: 'failed', error: 'LLM timeout after 120s', ...over,
  }
}

function mount(roomId = 'room-a') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LanguageProvider>
        <InterruptedAnswers roomId={roomId} />
      </LanguageProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.restoreAllMocks())

describe('interruptedSteps / partialPreview', () => {
  it('picks failed and timed-out steps of live tasks only', () => {
    const rows = interruptedSteps([
      task('in_progress', [['s1', 'done', 1], ['s2', 'failed', 2], ['s3', 'timeout', 3]]),
      task('done', [['s9', 'failed', 4]]),
      task('cancelled', [['s8', 'timeout', 5]]),
    ])
    expect(rows.map((r) => r.step.step_id)).toEqual(['s2', 's3'])
  })

  it('caps the preview and keeps short drafts whole', () => {
    expect(partialPreview('  ngắn  ')).toBe('ngắn')
    const long = 'x'.repeat(PARTIAL_PREVIEW_CHARS + 50)
    const out = partialPreview(long)
    expect(out.endsWith('…')).toBe(true)
    expect(out.length).toBe(PARTIAL_PREVIEW_CHARS + 1)
  })
})

describe('InterruptedAnswers', () => {
  it('renders nothing on the overview room and when no step is interrupted', async () => {
    const spy = vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue({
      tasks: [task('in_progress', [['s1', 'running', 1]])],
    })
    const { container, unmount } = mount('office')
    expect(spy).not.toHaveBeenCalled()
    unmount()

    mount('room-a')
    await waitFor(() => expect(spy).toHaveBeenCalledWith('room-a'))
    expect(container.querySelector('[data-testid="interrupted-answer"]')).toBeNull()
  })

  it('shows the partial draft, its sources, the error and the failure guide', async () => {
    vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue({
      tasks: [task('in_progress', [['s1', 'done', 1], ['s2', 'failed', 2]])],
    })
    const art = vi.spyOn(api, 'getStepArtifact').mockResolvedValue(artifact())
    mount()
    const card = await screen.findByTestId('interrupted-answer')
    await waitFor(() => expect(art).toHaveBeenCalledWith('t1', 2))
    expect(card.textContent).toContain(DICT.vi['interrupted.label'])
    expect(card.textContent).toContain('bước s2')
    await waitFor(() => expect(card.querySelector('.interrupted-answer-partial')?.textContent).toContain('Nháp'))
    expect(card.querySelectorAll('.citation-chip')).toHaveLength(2)
    expect(card.querySelector('.interrupted-answer-error')?.textContent).toContain('LLM timeout after 120s')
    expect(card.querySelector('.failure-guide')?.textContent).toContain(
      DICT.vi['failureGuide.step_failed.next'],
    )
  })

  it('says so when the dead step drafted nothing, and words a timeout as a timeout', async () => {
    vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue({
      tasks: [task('in_progress', [['s2', 'timeout', 0]])],
    })
    const art = vi.spyOn(api, 'getStepArtifact')
    mount()
    const card = await screen.findByTestId('interrupted-answer')
    // seq 0 = never dispatched: no artifact fetch at all.
    expect(art).not.toHaveBeenCalled()
    expect(card.textContent).toContain(DICT.vi['interrupted.noPartial'])
    expect(card.querySelector('.failure-guide')?.textContent).toContain(
      DICT.vi['failureGuide.step_timeout.why'],
    )
  })

  it('retry posts the step and surfaces a refusal inline', async () => {
    vi.spyOn(api, 'getRoomArtifacts').mockResolvedValue({
      tasks: [task('in_progress', [['s2', 'failed', 2]])],
    })
    vi.spyOn(api, 'getStepArtifact').mockResolvedValue(artifact({ result_text: '' }))
    const retry = vi.spyOn(api, 'retryStalledStep').mockRejectedValue(new Error('409 đã có người chạy lại'))
    mount()
    await screen.findByTestId('interrupted-answer')
    fireEvent.click(screen.getByRole('button', { name: DICT.vi['interrupted.retry'] }))
    await waitFor(() => expect(retry).toHaveBeenCalledWith('t1', 's2'))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(DICT.vi['stalledActions.retryFailed'])
    expect(alert.textContent).toContain('409 đã có người chạy lại')
  })
})
