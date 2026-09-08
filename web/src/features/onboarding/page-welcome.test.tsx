import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import { LanguageProvider } from '../../i18n/language-context'
import { EXAMPLE_BRIEF_KEYS, PageWelcome, type WelcomeHub } from './page-welcome'

function Probe() {
  const location = useLocation()
  const seed = (location.state as { assignSeed?: string } | null)?.assignSeed
  return <p data-testid="probe">{`${location.pathname}${location.search} ${seed ?? ''}`}</p>
}

function mount(hub: WelcomeHub, onPick?: (b: string) => void) {
  return render(
    <LanguageProvider>
      <MemoryRouter initialEntries={['/work']}>
        <Routes>
          <Route path="/work" element={<PageWelcome hub={hub} onPick={onPick} />} />
          <Route path="/chat" element={<Probe />} />
          <Route path="/team" element={<Probe />} />
        </Routes>
      </MemoryRouter>
    </LanguageProvider>,
  )
}

describe('PageWelcome', () => {
  it('lists the example briefs and hands the picked one to the chat hub as a seed', () => {
    mount('work')
    expect(screen.getByTestId('page-welcome').textContent).toContain(DICT.vi['welcome.work.title'])
    const chips = screen.getAllByRole('button').filter((b) => b.className.includes('page-welcome-brief'))
    expect(chips.map((c) => c.textContent)).toEqual(EXAMPLE_BRIEF_KEYS.map((k) => DICT.vi[k]))
    fireEvent.click(chips[1])
    expect(screen.getByTestId('probe').textContent).toBe(`/chat ${DICT.vi['welcome.brief.posts']}`)
  })

  it('on the chat hub the pick stays in place through onPick', () => {
    const onPick = vi.fn()
    mount('chat', onPick)
    fireEvent.click(screen.getByRole('button', { name: DICT.vi['welcome.brief.report'] }))
    expect(onPick).toHaveBeenCalledWith(DICT.vi['welcome.brief.report'])
    expect(screen.queryByTestId('probe')).toBeNull()
  })

  it('the team hub adds a hire shortcut that opens the hire panel', () => {
    mount('team')
    fireEvent.click(screen.getByRole('button', { name: DICT.vi['welcome.team.hire'] }))
    expect(screen.getByTestId('probe').textContent).toBe('/team?hire=1 ')
  })
})
