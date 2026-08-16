// A speech bubble above a desk showing the agent's current task/step title (+ optional M31
// self-check/rework phase tag). Implemented as an HTML overlay (drei's <Html>) which projects
// the given world position to screen space every frame — cheaper and crisper for text than a
// texture-mapped 3D plane. Renders nothing when there is no title. The bubble is a FIXED-width
// frame: long titles are truncated with "…" (CSS ellipsis per line) so bubbles never stretch
// across the scene or overlap their neighbours' desks.
import { Html } from '@react-three/drei'
import { DICT } from '../../i18n/dictionary'
import type { UiKey } from '../../i18n/dictionary'
import { PHASE_LABEL } from '../office-shared/phase-labels'

interface SpeechBubbleProps {
  position: [number, number, number]
  taskTitle: string | null
  stepTitle: string | null
  phase?: string | null
  // M33: the colleague id this desk is currently consulting/being consulted by, or
  // null. Event-driven (`AgentDeskState.consultWith`, see agent-office-state.ts) — no
  // timer here either, this component just renders whatever the reducer currently
  // holds.
  consultWith?: string | null
  // v15: desk belongs to a PIC of at least one running task (AgentDeskState.picTasks).
  isPic?: boolean
  // Dual-lens P1: the desk's last step failed — lead the bubble with a ⚠ tag.
  isError?: boolean
  // v53 i18n: renders inside <Canvas>, so it cannot call useLanguage() itself — the
  // translate function is threaded down as a prop (see agent-desk.tsx). Optional so the
  // (untested-in-isolation) default keeps working with the vi text if ever omitted.
  t?: (key: UiKey, params?: Record<string, string | number>) => string
}

export function SpeechBubble({
  position, taskTitle, stepTitle, phase, consultWith, isPic, isError, t,
}: SpeechBubbleProps) {
  if (!taskTitle && !consultWith && !isError) return null
  const tr = t ?? ((key: UiKey, params?: Record<string, string | number>) => {
    let s: string = DICT.vi[key]
    if (params) for (const [k, v] of Object.entries(params)) s = s.replaceAll(`{${k}}`, String(v))
    return s
  })
  const phaseKey = phase ? PHASE_LABEL[phase] : undefined
  const phaseLabel = phaseKey ? tr(phaseKey) : undefined
  return (
    <Html position={position} center distanceFactor={8} occlude={false}>
      <div className={isError ? 'office-3d-bubble office-3d-bubble-has-error' : 'office-3d-bubble'}>
        {isError && <span className="office-3d-bubble-error">{tr('speechBubble.error')}</span>}
        {isPic && <span className="office-3d-bubble-pic">PIC</span>}
        {taskTitle && <strong title={taskTitle}>{taskTitle}</strong>}
        {stepTitle && (
          <span className="office-3d-bubble-step" title={stepTitle}>
            {stepTitle}
          </span>
        )}
        {phaseLabel && <span className="office-3d-bubble-phase">{phaseLabel}</span>}
        {consultWith && (
          <span
            className="office-3d-bubble-consult"
            title={tr('speechBubble.consultingTitle', { name: consultWith })}
          >
            💬 {consultWith}
          </span>
        )}
      </div>
    </Html>
  )
}
