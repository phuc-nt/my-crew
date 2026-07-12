// The coordinator's round table — always at the center, static (no tween, no state
// machine: the coordinator is always "present"). v32 solid look: warm round table on
// the rug, visually distinct from the staff desks at a glance.
import { Html } from '@react-three/drei'
import { officeTheme } from './desk-colors'

export function CoordinatorDesk({ dark = false }: { dark?: boolean }) {
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
        <div className="office-3d-label office-3d-label-coordinator">trưởng phòng</div>
      </Html>
    </group>
  )
}
