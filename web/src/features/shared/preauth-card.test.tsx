// The pre-authorization card: which flags a step shows, when the scope choice appears
// at all, and that picking "always" reaches the parent as the wire value.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../../i18n/language-context'
import type { AssignManifest, AssignManifestStep } from '../../types'
import { PreauthCard, scopeChoiceNeeded, stepFlags } from './preauth-card'

const internal: AssignManifestStep = {
  step_id: 's1', title: 'soạn nội dung', assigned_to: 'content',
  external_write: false, needs_shell: false, needs_web: false, needs_mail: false, needs_review: false,
}
const mail: AssignManifestStep = {
  ...internal, step_id: 's2', title: 'gửi email khách', assigned_to: 'assistant',
  external_write: true, needs_mail: true, needs_review: true,
}

function card(manifest: AssignManifest | undefined, onScopeChange = vi.fn(), scope: '' | 'once' | 'always' = '') {
  render(
    <LanguageProvider>
      <PreauthCard manifest={manifest} scope={scope} onScopeChange={onScopeChange} />
    </LanguageProvider>,
  )
  return onScopeChange
}

describe('stepFlags / scopeChoiceNeeded', () => {
  it('lists only the flags a step carries, in display order', () => {
    expect(stepFlags(internal)).toEqual([])
    expect(stepFlags(mail)).toEqual(['external_write', 'needs_mail', 'needs_review'])
  })
  it('asks for a scope only when some step will hit a gate', () => {
    expect(scopeChoiceNeeded(undefined)).toBe(false)
    expect(scopeChoiceNeeded({ steps: [internal], external_count: 0 })).toBe(false)
    expect(scopeChoiceNeeded({ steps: [mail], external_count: 1 })).toBe(true)
  })
})

describe('PreauthCard', () => {
  it('renders nothing without a manifest (old backends)', () => {
    card(undefined)
    expect(screen.queryByTestId('preauth-card')).toBeNull()
  })

  it('shows the internal tag and no scope choice when nothing touches the outside', () => {
    card({ steps: [internal], external_count: 0 })
    expect(screen.getByText('soạn nội dung')).toBeInTheDocument()
    expect(document.querySelector('.preauth-flag.is-internal')).not.toBeNull()
    expect(screen.queryByTestId('preauth-scope')).toBeNull()
    expect(screen.getByText(/Không bước nào chạm ra ngoài/)).toBeInTheDocument()
  })

  it('flags the gated step, counts it in the legend and reports the picked scope', () => {
    const onScopeChange = card({ steps: [internal, mail], external_count: 1 })
    expect(document.querySelector('.preauth-step.is-external .preauth-step-title')?.textContent)
      .toBe('gửi email khách')
    expect(document.querySelector('.preauth-flag.is-needs_mail')).not.toBeNull()
    expect(screen.getByText(/^1 bước sẽ hỏi duyệt/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/ghi thành luật/))
    expect(onScopeChange).toHaveBeenCalledWith('always')
  })

  it('marks the current scope as the checked radio', () => {
    card({ steps: [mail], external_count: 1 }, vi.fn(), 'once')
    const once = screen.getByLabelText(/chỉ việc này/) as HTMLInputElement
    expect(once.checked).toBe(true)
    expect(document.querySelectorAll('.preauth-choice.is-on').length).toBe(1)
  })
})
