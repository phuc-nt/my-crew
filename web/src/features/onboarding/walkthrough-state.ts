// v96: the first-visit walkthrough's data — which four things a new CEO is shown, in
// what order, and the flag that says it has been seen. Pure so the card component
// only renders and the test needs no DOM.
import type { UiKey } from '../../i18n/dictionary'

export const WALKTHROUGH_STORAGE_KEY = 'my-crew.walkthrough.done'

/** Window event that re-opens the walkthrough (from the shortcuts card). */
export const WALKTHROUGH_OPEN_EVENT = 'my-crew:walkthrough-open'

export interface WalkthroughStep {
  id: string
  /** The `data-walkthrough` value of the element the step points at. */
  anchor: string
  titleKey: UiKey
  bodyKey: UiKey
}

export const WALKTHROUGH_STEPS: readonly WalkthroughStep[] = [
  { id: 'hubs', anchor: 'hubs', titleKey: 'walkthrough.hubs.title', bodyKey: 'walkthrough.hubs.body' },
  {
    id: 'composer',
    anchor: 'composer',
    titleKey: 'walkthrough.composer.title',
    bodyKey: 'walkthrough.composer.body',
  },
  { id: 'bell', anchor: 'bell', titleKey: 'walkthrough.bell.title', bodyKey: 'walkthrough.bell.body' },
  {
    id: 'palette',
    anchor: 'shortcuts',
    titleKey: 'walkthrough.palette.title',
    bodyKey: 'walkthrough.palette.body',
  },
]

export function readWalkthroughDone(): boolean {
  try {
    return localStorage.getItem(WALKTHROUGH_STORAGE_KEY) === '1'
  } catch {
    // No storage → never nag: a walkthrough that returns on every load is worse than none.
    return true
  }
}

export function writeWalkthroughDone(): void {
  try {
    localStorage.setItem(WALKTHROUGH_STORAGE_KEY, '1')
  } catch {
    // Nothing to do: the card closes for this page load regardless.
  }
}

/** Class put on the anchored element while its step is showing. */
export const WALKTHROUGH_ANCHOR_CLASS = 'is-walkthrough-anchor'

export function anchorSelector(step: WalkthroughStep): string {
  return `[data-walkthrough="${step.anchor}"]`
}
