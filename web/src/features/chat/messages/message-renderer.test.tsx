// The one branch worth a component test: a `done` milestone is markdown, everything else
// is plain text. Real deliverables arrive as full documents (headings, GFM tables), and
// rendering those as a text node was a defect only visible on real data.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LanguageProvider } from '../../../i18n/language-context'
import type { ThreadItem } from '../chat-state'
import { MessageRow } from './message-renderer'

function row(item: ThreadItem) {
  return render(
    <LanguageProvider>
      <ul><MessageRow item={item} /></ul>
    </LanguageProvider>,
  )
}

const base = { seq: 1, ts: '2026-08-19T09:00:00Z', author: 'coordinator' } as const

describe('MessageRow', () => {
  it('renders a delivered milestone as markdown, not literal syntax', () => {
    const { container } = row({
      ...base,
      kind: 'milestone',
      body: {
        milestone: 'done',
        message: '# Báo cáo\n\n**Notion** miễn phí.\n\n| Công cụ | Giá |\n|---|---|\n| Notion | 0đ |',
      },
    })
    // The markers themselves must be gone — that is the whole point of the branch.
    expect(container.textContent).not.toContain('**')
    expect(container.textContent).not.toContain('|---|')
    expect(container.querySelector('table')).not.toBeNull()
    expect(container.querySelectorAll('table td').length).toBe(2)
    expect(screen.getByText('Notion', { selector: 'strong' })).toBeTruthy()
  })

  it('leaves a status milestone as plain text', () => {
    // `stuck` is a notice, not a deliverable: no markdown pass, and it stays clamped.
    const { container } = row({
      ...base,
      kind: 'milestone',
      body: { milestone: 'stuck', message: 'Việc **kẹt** ở bước 2.' },
    })
    expect(container.querySelector('.is-markdown')).toBeNull()
    expect(container.querySelector('.chat-row-text.is-clamped')).not.toBeNull()
    // The asterisks survive precisely because this branch does not parse markdown.
    expect(container.textContent).toContain('**kẹt**')
  })
})
