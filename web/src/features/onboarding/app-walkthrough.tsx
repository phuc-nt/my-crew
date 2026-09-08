// v96: a four-step first-visit tour. One small card pinned to the corner, one element
// highlighted per step, and two ways out (skip, finish) that both remember the choice —
// it shows exactly once unless the CEO asks for it again from the shortcuts card.
//
// It highlights by class rather than by measuring positions: the anchors live in the
// shell and the chat composer, both of which reflow with the viewport, and a card that
// follows them would need a resize observer for a benefit nobody asked for.
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import {
  WALKTHROUGH_ANCHOR_CLASS,
  WALKTHROUGH_OPEN_EVENT,
  WALKTHROUGH_STEPS,
  anchorSelector,
  readWalkthroughDone,
  writeWalkthroughDone,
} from './walkthrough-state'

export function AppWalkthrough() {
  const { t } = useLanguage()
  // null = closed. The initial read is synchronous so the card is in the first paint.
  const [step, setStep] = useState<number | null>(() => (readWalkthroughDone() ? null : 0))

  useEffect(() => {
    const onOpen = () => setStep(0)
    window.addEventListener(WALKTHROUGH_OPEN_EVENT, onOpen)
    return () => window.removeEventListener(WALKTHROUGH_OPEN_EVENT, onOpen)
  }, [])

  // Highlight the current step's anchor for as long as the step shows.
  useEffect(() => {
    if (step === null) return
    const el = document.querySelector(anchorSelector(WALKTHROUGH_STEPS[step]))
    if (!el) return
    el.classList.add(WALKTHROUGH_ANCHOR_CLASS)
    return () => el.classList.remove(WALKTHROUGH_ANCHOR_CLASS)
  }, [step])

  if (step === null) return null
  const current = WALKTHROUGH_STEPS[step]
  const last = step === WALKTHROUGH_STEPS.length - 1

  const finish = () => {
    writeWalkthroughDone()
    setStep(null)
  }

  return (
    <aside
      className="walkthrough"
      role="dialog"
      aria-label={t('walkthrough.title')}
      data-testid="walkthrough"
      data-step={current.id}
    >
      <p className="walkthrough-progress muted">
        {t('walkthrough.title')} · {t('walkthrough.stepOf', { n: step + 1, total: WALKTHROUGH_STEPS.length })}
      </p>
      <h3 className="walkthrough-heading">{t(current.titleKey)}</h3>
      <p className="walkthrough-body">{t(current.bodyKey)}</p>
      <div className="walkthrough-actions">
        <Button variant="ghost" onClick={finish}>
          {t('walkthrough.skip')}
        </Button>
        {last ? (
          <Button variant="primary" onClick={finish}>
            {t('walkthrough.done')}
          </Button>
        ) : (
          <Button variant="primary" onClick={() => setStep(step + 1)}>
            {t('walkthrough.next')}
          </Button>
        )}
      </div>
    </aside>
  )
}
