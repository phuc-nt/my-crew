// v54 P4: three CHEAP 3D desk indicators (CEO decision — no new geometry systems, no new
// useFrame loops, no animation work). Split out of agent-desk.tsx to keep that file under
// the ~300-line modularization guideline — these are pure render helpers, all their
// on/off logic already decided by agent-office-state.ts (this file only reads props).
//
// ✋ pending badge + ×N fan-out badge are Html overlays (same drei <Html> pattern the
// desk tooltip/label already use); the deep_team ghost is ONE static translucent mesh
// (reuses the avatar's own capsule+sphere geometry, opacity ~0.35, no useFrame).
import { Html } from '@react-three/drei'
import type { UiKey } from '../../i18n/dictionary'
import { DICT } from '../../i18n/dictionary'

interface DeskStatusBadgesProps {
  position: [number, number, number]
  pendingCount: number
  concurrentSteps: number
  t?: (key: UiKey, params?: Record<string, string | number>) => string
}

// Html overlay row for ✋ (pending) / ×N (fan-out) — rendered together above the desk
// label so both can show at once without overlapping. Renders nothing when neither
// condition holds (no empty wrapper left mounted).
export function DeskStatusBadges({ position, pendingCount, concurrentSteps, t }: DeskStatusBadgesProps) {
  const tr = t ?? ((key: UiKey) => DICT.vi[key])
  const showPending = pendingCount > 0
  const showFanOut = concurrentSteps >= 2
  if (!showPending && !showFanOut) return null
  return (
    <Html position={position} center distanceFactor={10} occlude={false}>
      <div className="office-3d-desk-badges">
        {showPending && (
          <span
            className="office-3d-badge office-3d-badge-pending"
            title={tr('agentDesk.pendingBadgeTitle', { n: pendingCount })}
          >
            ✋{pendingCount > 1 ? ` ${pendingCount}` : ''}
          </span>
        )}
        {showFanOut && (
          <span
            className="office-3d-badge office-3d-badge-fanout"
            title={tr('agentDesk.fanOutBadgeTitle', { n: concurrentSteps })}
          >
            ×{concurrentSteps}
          </span>
        )}
      </div>
    </Html>
  )
}

interface DeepTeamGhostProps {
  position: [number, number, number]
  color: string
  skin: string
}

// One small translucent low-poly figure next to the avatar — reuses the SAME
// capsule-body + sphere-head shapes AgentAvatar (agent-desk.tsx) builds, at a smaller
// scale and fixed opacity, with NO accessory and NO useFrame (static — the "no new
// animation" constraint). Signals "a subagent is helping" without a second real avatar.
export function DeepTeamGhost({ position, color, skin }: DeepTeamGhostProps) {
  return (
    <group position={position} scale={0.65}>
      <mesh position={[0, 0.42, 0]}>
        <capsuleGeometry args={[0.19, 0.34, 4, 8]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.88, 0]}>
        <sphereGeometry args={[0.16, 16, 12]} />
        <meshBasicMaterial color={skin} transparent opacity={0.35} depthWrite={false} />
      </mesh>
    </group>
  )
}
