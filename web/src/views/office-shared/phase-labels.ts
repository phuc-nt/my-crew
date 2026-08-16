// Closed-set phase tag -> dictionary key, shared by the 3D speech bubble and the 2D
// message line. Matches `team_task_graph.py`'s PHASE_WORK/PHASE_SELF_CHECK/PHASE_REWORK
// constants — an unrecognized tag (future phase value not yet wired here) renders
// nothing rather than the raw code.
//
// Lives here (not in office-3d/speech-bubble.tsx where it started) because the message
// line is in the EAGER bundle: importing it from the bubble dragged @react-three/drei —
// and with it all of three.js core — into the main index chunk for every page load.
import type { UiKey } from '../../i18n/dictionary'

export const PHASE_LABEL: Record<string, UiKey> = {
  'dang-lam': 'speechBubble.phaseWork',
  'tu-soat': 'speechBubble.phaseSelfCheck',
  'dang-sua': 'speechBubble.phaseRework',
  'nho-tro-giup': 'speechBubble.phaseNeedHelp',
}
