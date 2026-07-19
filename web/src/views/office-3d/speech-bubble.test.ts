// SpeechBubble itself cannot render in jsdom (drei's <Html> requires a live Fiber/Canvas
// context — see office-unified.test.tsx's note on the same constraint), so this covers the
// piece of its logic that can be verified without a Canvas: the phase-tag vocabulary the
// 3D bubble is supposed to render must exactly match the backend's phase constants
// (team_task_graph.py's PHASE_WORK/PHASE_SELF_CHECK/PHASE_REWORK/PHASE_RECOVER). A regression here — the
// map going empty/renamed, or agent-desk.tsx failing to pass `phase` through to
// `<SpeechBubble>` at all — is the exact class of bug that left the 3D phase render dead
// (the map existed and was correct, but nothing fed it a value).
import { expect, test } from 'vitest'
import { DICT } from '../../i18n/dictionary'
import { PHASE_LABEL } from './speech-bubble'

test('PHASE_LABEL covers exactly the backend phase vocabulary', () => {
  expect(PHASE_LABEL).toEqual({
    'dang-lam': 'speechBubble.phaseWork',
    'tu-soat': 'speechBubble.phaseSelfCheck',
    'dang-sua': 'speechBubble.phaseRework',
    'nho-tro-giup': 'speechBubble.phaseNeedHelp',
  })
  // Each key must resolve to a real vi dictionary entry — the map's job is routing to
  // the dictionary, not holding the text itself anymore.
  for (const key of Object.values(PHASE_LABEL)) {
    expect(DICT.vi[key]).toBeTruthy()
  }
})

test('an unrecognized phase tag has no label (renders nothing, not the raw code)', () => {
  expect(PHASE_LABEL['unknown-future-phase']).toBeUndefined()
})
