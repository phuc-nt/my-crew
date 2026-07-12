// Solid floor slab + center rug (v32 low-poly flat — replaces the wireframe grid).
// Pure geometry, no state; theme rides in as a prop (r3f can't read CSS vars).
import { officeTheme } from './desk-colors'

const FLOOR_SIZE: [number, number, number] = [16, 0.3, 11]

export function OfficeFloor({ dark = false }: { dark?: boolean }) {
  const theme = officeTheme(dark)
  return (
    <group>
      <mesh position={[0, -0.15, 0]} receiveShadow>
        <boxGeometry args={FLOOR_SIZE} />
        <meshLambertMaterial color={theme.floor} />
      </mesh>
      {/* round rug under the coordinator table — anchors the room center */}
      <mesh position={[0, 0.03, 0]} receiveShadow>
        <cylinderGeometry args={[2.2, 2.2, 0.05, 32]} />
        <meshLambertMaterial color={theme.rug} />
      </mesh>
    </group>
  )
}
