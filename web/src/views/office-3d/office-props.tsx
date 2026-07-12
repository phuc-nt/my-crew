// Static office furniture (v32 solid low-poly): potted plants + a whiteboard. Pure
// decoration — props never react to the SSE stream. Positions sit OUTSIDE the desk
// ring (see desk-layout.ts) so they never collide with a desk.
const POT_COLOR = '#d97b66'
const LEAF_COLOR = '#84cc8f'
const BOARD_COLOR = '#f4f7fa'
const BOARD_FRAME = '#93a3b8'

function PottedPlant({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.15, 0]} castShadow>
        <cylinderGeometry args={[0.22, 0.16, 0.3, 12]} />
        <meshLambertMaterial color={POT_COLOR} />
      </mesh>
      <mesh position={[0, 0.68, 0]} castShadow>
        <icosahedronGeometry args={[0.42, 0]} />
        <meshLambertMaterial color={LEAF_COLOR} flatShading />
      </mesh>
    </group>
  )
}

function Whiteboard({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh position={[0, 1.05, 0]} castShadow>
        <boxGeometry args={[1.7, 1.0, 0.06]} />
        <meshLambertMaterial color={BOARD_COLOR} />
      </mesh>
      {[-0.7, 0.7].map((x) => (
        <mesh key={x} position={[x, 0.45, 0]}>
          <cylinderGeometry args={[0.04, 0.04, 1.1, 8]} />
          <meshLambertMaterial color={BOARD_FRAME} />
        </mesh>
      ))}
    </group>
  )
}

export function OfficeProps() {
  return (
    <group>
      <PottedPlant position={[6.6, 0, -3.6]} />
      <PottedPlant position={[-6.6, 0, 3.6]} />
      <Whiteboard position={[0, 0, -4.9]} />
    </group>
  )
}
