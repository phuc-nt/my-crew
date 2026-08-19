// v56: the artifact drawer's modal a11y (focus trap + restore, Esc close) and the
// error line carrying HTTP status + backend detail (ApiError from client.ts).
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '../../api/client'
import { LanguageProvider } from '../../i18n/language-context'
import { UiModeProvider } from '../../ui-mode-context'
import { ArtifactViewer } from './artifact-viewer'

afterEach(() => vi.restoreAllMocks())

const ARTIFACT = {
  task_id: 't1',
  step_title: 'Bước tổng hợp',
  result_text: '# Kết quả tuần',
  attempt: 'a1',
  self_check_failed: false,
}

function renderViewer(onClose = vi.fn()) {
  const view = render(
    <LanguageProvider>
      <UiModeProvider>
        <ArtifactViewer taskId="t1" seq={1} stepId="s1" onClose={onClose} />
      </UiModeProvider>
    </LanguageProvider>,
  )
  return { view, onClose }
}

test('lỗi API hiện HTTP status + detail của backend', async () => {
  vi.spyOn(api, 'getStepArtifact').mockRejectedValue(new ApiError(404, 'artifact đã bị dọn'))
  renderViewer()
  await screen.findByText(/HTTP 404 — artifact đã bị dọn/)
})

test('lỗi không phải ApiError giữ message nguyên trạng (không status giả)', async () => {
  vi.spyOn(api, 'getStepArtifact').mockRejectedValue(new Error('network down'))
  renderViewer()
  const line = await screen.findByText(/network down/)
  expect(line.textContent).not.toContain('HTTP')
})

test('focus trap: vào drawer khi mở, Tab quay vòng, unmount trả focus về chỗ cũ', async () => {
  vi.spyOn(api, 'getStepArtifact').mockResolvedValue(ARTIFACT)
  const outside = document.createElement('button')
  outside.textContent = 'ngoài drawer'
  document.body.appendChild(outside)
  outside.focus()

  const { view } = renderViewer()
  await screen.findByText('Bước tổng hợp')
  // Initial focus moved INTO the drawer (the close button — the only tabbable enabled
  // at mount; copy/download unlock when the artifact lands).
  const drawer = document.querySelector('.artifact-drawer')!
  expect(drawer.contains(document.activeElement)).toBe(true)

  // Tab on the LAST tabbable wraps to the first (now-enabled copy button).
  const buttons = Array.from(drawer.querySelectorAll('button'))
  const first = buttons[0]
  const last = buttons[buttons.length - 1]
  last.focus()
  fireEvent.keyDown(last, { key: 'Tab' })
  expect(document.activeElement).toBe(first)

  // Shift+Tab on the FIRST wraps back to the last.
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)

  // Closing restores focus to the element that had it before the drawer opened.
  view.unmount()
  expect(document.activeElement).toBe(outside)
  outside.remove()
})

test('Esc đóng drawer', async () => {
  vi.spyOn(api, 'getStepArtifact').mockResolvedValue(ARTIFACT)
  const { onClose } = renderViewer()
  await screen.findByText('Bước tổng hợp')
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
})

test('v82: chế độ nâng cao có tab Quá trình; chế độ thường thì không', async () => {
  vi.spyOn(api, 'getStepArtifact').mockResolvedValue(ARTIFACT)
  const getTranscript = vi.spyOn(api, 'getStepTranscript').mockResolvedValue({
    task_id: 't1', step_id: 's1', seq: 1, attempts: 1,
    events: [{ t: 'tool_call', name: 'web_search', args_head: 'q=x' }],
  })

  // low (mặc định): không render tab bar
  const first = renderViewer()
  await screen.findByText('Bước tổng hợp')
  expect(screen.queryByRole('tab')).toBeNull()
  first.view.unmount()

  // high: tab bar xuất hiện, bấm "Quá trình" tải transcript. jsdom ở đây không có
  // localStorage hoạt động — stub như ui-mode-context.test.tsx rồi gỡ ngay sau đó.
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (k === 'ui-mode' ? 'high' : null),
    setItem: () => undefined,
    removeItem: () => undefined,
  })
  try {
    renderViewer()
    await screen.findByText('Bước tổng hợp')
    fireEvent.click(screen.getByRole('tab', { name: 'Quá trình' }))
    await screen.findByText(/web_search/)
    expect(getTranscript).toHaveBeenCalledWith('t1', 1)
  } finally {
    vi.unstubAllGlobals()
  }
})
