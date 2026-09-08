import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { BackgroundActivityDrawer, isSubagentActivity } from './background-activity-drawer'
import type { ActivityLine } from './chat-state'

const LINES: ActivityLine[] = [
  { task: 't1', step: 's1', tool: 'web_search', count: 3, agent: 'researcher', ts: '2026-09-08T01:00:00Z', phase: 'calling-tool' },
  { task: 't1', step: 's2', tool: 'task', count: 1, agent: 'content', ts: '2026-09-08T01:00:05Z', phase: 'calling-tool' },
  { task: 't2', step: 's9', tool: '', count: 2, agent: 'ke-toan', ts: '2026-09-08T01:00:09Z', phase: 'writing' },
]

function drawer(activities: ActivityLine[]) {
  return render(
    <LanguageProvider>
      <BackgroundActivityDrawer activities={activities} />
    </LanguageProvider>,
  )
}

describe('BackgroundActivityDrawer', () => {
  it('renders nothing without live activity', () => {
    const { container } = drawer([])
    expect(container.querySelector('[data-testid="background-activity"]')).toBeNull()
  })

  it('folds the lines behind a count, names the subagents, and shows the newest line inline', () => {
    drawer(LINES)
    expect(screen.getByTestId('background-activity-count').textContent).toBe('3')
    expect(screen.getByTestId('background-activity-subagents').textContent).toBe(
      DICT.vi['backgroundActivity.subagents'].replace('{n}', '1'),
    )
    // Collapsed: only the head, wording for the newest ('writing') line.
    expect(screen.queryByRole('list')).toBeNull()
    expect(screen.getByRole('button').textContent).toContain(
      DICT.vi['backgroundActivity.writingLine'].replace('{step}', 's9'),
    )
  })

  it('expands to every line, marking the subagent one', () => {
    drawer(LINES)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('button').getAttribute('aria-expanded')).toBe('true')
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0].textContent).toContain('researcher')
    expect(items[0].textContent).toContain('web_search')
    expect(items[1].className).toContain('is-subagent')
    expect(items[1].textContent).toContain(
      DICT.vi['backgroundActivity.subagentLine'].replace('{step}', 's2').replace('{count}', '1'),
    )
    expect(items[2].className).not.toContain('is-subagent')
    expect(isSubagentActivity(LINES[1])).toBe(true)
    expect(isSubagentActivity(LINES[0])).toBe(false)
  })
})
