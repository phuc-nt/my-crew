// v33 P4: clarify section — renders pending questions, option button answers in one
// click, free-text answers, 409 (answered elsewhere) refreshes silently. Mocked api.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { DICT } from '../i18n/dictionary'
import { LanguageProvider } from '../i18n/language-context'
import { ClarifySection } from './clarify-section'

function renderClarify() {
  return render(
    <LanguageProvider>
      <ClarifySection />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

const pending = {
  questions: [
    {
      id: 7, agent_id: 'nghien-cuu', task_id: 'task12345678',
      question: 'Ưu tiên chi phí hay tốc độ?', options: ['Chi phí', 'Tốc độ'],
      asked_at: '2026-07-13T00:00:00+00:00', expires_at: '2026-07-15T00:00:00+00:00',
    },
  ],
}

test('renders the question with its option buttons', async () => {
  vi.spyOn(api, 'getClarifyPending').mockResolvedValue(pending)
  renderClarify()

  expect(await screen.findByText(/Ưu tiên chi phí hay tốc độ\?/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Chi phí' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Tốc độ' })).toBeInTheDocument()
})

test('option click answers and refreshes the list', async () => {
  const get = vi
    .spyOn(api, 'getClarifyPending')
    .mockResolvedValueOnce(pending)
    .mockResolvedValueOnce({ questions: [] })
  const answer = vi.spyOn(api, 'answerClarify').mockResolvedValue({ ok: true, id: 7 })
  renderClarify()

  fireEvent.click(await screen.findByRole('button', { name: 'Tốc độ' }))
  await waitFor(() => expect(answer).toHaveBeenCalledWith(7, 'Tốc độ'))
  await waitFor(() =>
    expect(screen.queryByText(/Ưu tiên chi phí hay tốc độ\?/)).not.toBeInTheDocument(),
  )
  expect(get).toHaveBeenCalledTimes(2)
})

test('free-text answer sends on Gửi', async () => {
  vi.spyOn(api, 'getClarifyPending')
    .mockResolvedValueOnce(pending)
    .mockResolvedValueOnce({ questions: [] })
  const answer = vi.spyOn(api, 'answerClarify').mockResolvedValue({ ok: true, id: 7 })
  renderClarify()

  fireEvent.change(await screen.findByPlaceholderText(DICT.vi['clarify.freeTextPlaceholder']), {
    target: { value: 'Cân bằng cả hai, ưu tiên deadline' },
  })
  fireEvent.click(screen.getByRole('button', { name: DICT.vi['clarify.send'] }))
  await waitFor(() =>
    expect(answer).toHaveBeenCalledWith(7, 'Cân bằng cả hai, ưu tiên deadline'),
  )
})

test('answered-elsewhere (409) refreshes without showing an error', async () => {
  vi.spyOn(api, 'getClarifyPending')
    .mockResolvedValueOnce(pending)
    .mockResolvedValueOnce({ questions: [] })
  vi.spyOn(api, 'answerClarify').mockRejectedValue(
    new Error('Câu hỏi này đã được trả lời hoặc đã hết hạn.'),
  )
  renderClarify()

  fireEvent.click(await screen.findByRole('button', { name: 'Chi phí' }))
  await waitFor(() =>
    expect(screen.queryByText(/Ưu tiên chi phí hay tốc độ\?/)).not.toBeInTheDocument(),
  )
  expect(screen.queryByText(/đã được trả lời/)).not.toBeInTheDocument()
})

test('renders nothing when there are no questions', async () => {
  vi.spyOn(api, 'getClarifyPending').mockResolvedValue({ questions: [] })
  const { container } = renderClarify()
  await waitFor(() => expect(api.getClarifyPending).toHaveBeenCalled())
  expect(container.querySelector('.clarify-section')).toBeNull()
})
