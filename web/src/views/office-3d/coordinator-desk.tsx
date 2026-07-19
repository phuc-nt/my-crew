// The coordinator's round table — always at the center, static (no tween, no state
// machine: the coordinator is always "present"). v32 solid look: warm round table on
// the rug, visually distinct from the staff desks at a glance.
import { Html } from '@react-three/drei'
import type { UiKey } from '../../i18n/dictionary'
import { DICT } from '../../i18n/dictionary'
import { DeskStatusBadges } from './desk-badges'
import { officeTheme } from './desk-colors'

interface CoordinatorDeskProps {
  dark?: boolean
  // Pending approvals/clarify whose owner has no staff desk (the coordinator itself,
  // asking on a task's behalf) — shown as the same ✋ badge the staff desks use.
  pendingCount?: number
  // v53 i18n: renders inside <Canvas>, so it cannot call useLanguage() itself — the
  // translate function is threaded down as a prop from office-canvas.tsx (same pattern
  // as agent-desk.tsx). Optional so the (untested-in-isolation) default keeps working
  // with the vi text if ever omitted.
  t?: (key: UiKey, params?: Record<string, string | number>) => string
}

export function CoordinatorDesk({ dark = false, pendingCount = 0, t }: CoordinatorDeskProps) {
  const tr = t ?? ((key: UiKey) => DICT.vi[key])
  const theme = officeTheme(dark)
  return (
    <group>
      <mesh position={[0, 0.72, 0]} castShadow>
        <cylinderGeometry args={[0.9, 0.9, 0.12, 24]} />
        <meshLambertMaterial color={theme.tableTop} />
      </mesh>
      <mesh position={[0, 0.36, 0]}>
        <cylinderGeometry args={[0.12, 0.3, 0.72, 12]} />
        <meshLambertMaterial color={theme.tableLeg} />
      </mesh>
      <Html position={[0, 1.15, 0]} center distanceFactor={10} occlude={false}>
        <div className="office-3d-label office-3d-label-coordinator">{tr('coordinatorDesk.label')}</div>
      </Html>
      <DeskStatusBadges position={[0, 1.5, 0]} pendingCount={pendingCount} concurrentSteps={0} t={t} />
    </group>
  )
}
