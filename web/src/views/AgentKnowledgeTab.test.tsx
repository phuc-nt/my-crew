// v9 P2: the Knowledge tab has 4 independent Save buttons (SOUL/PROJECT/skills/company-docs).
// A CEO editing several sections may click one Save and think everything saved. Each section
// tracks its own dirty state and shows a "● Chưa lưu" badge until saved, so unsaved work in a
// section is visible. Mocked api, no network.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { LanguageProvider } from '../i18n/language-context'
import { KnowledgeTab } from './AgentKnowledgeTab'

function renderTab(id: string) {
  return render(
    <LanguageProvider>
      <KnowledgeTab id={id} />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getKnowledge').mockResolvedValue({
    doc: 'soul',
    raw_mode: false,
    fields: { role: '', tone: '', rules: '' },
    raw: '',
  } as never)
  vi.spyOn(api, 'getSkills').mockResolvedValue({
    skills: [{ name: 'triage', description: 'phân loại', selected: false }],
  } as never)
  vi.spyOn(api, 'getAgentCompanyDocs').mockResolvedValue({
    docs: [{ slug: 'leave', title: 'Nghỉ phép', selected: false }],
  } as never)
})

test('editing a skills checkbox marks the section unsaved, clearing after save', async () => {
  const putSkills = vi.spyOn(api, 'putSkills').mockResolvedValue({ skills: [] } as never)
  renderTab('acme')

  // toggle the skill → its section shows "● Chưa lưu"
  fireEvent.click(await screen.findByText('triage'))
  expect(screen.getByText(/Chưa lưu/)).toBeInTheDocument()

  // save the skills section → the unsaved badge clears
  fireEvent.click(screen.getByText('Lưu kỹ năng'))
  await waitFor(() => expect(putSkills).toHaveBeenCalledWith('acme', ['triage']))
  await waitFor(() => expect(screen.queryByText(/Chưa lưu/)).not.toBeInTheDocument())
})

test('a fresh tab has no unsaved badges', async () => {
  renderTab('acme')
  await screen.findByText('triage')
  expect(screen.queryByText(/Chưa lưu/)).not.toBeInTheDocument()
})
