// The 3D office Canvas, props-in only (v15): the unified office screen owns the ONE SSE
// stream and passes derived state down to both this canvas and the text activity feed —
// the two surfaces can never disagree. v32 "đại tu visual": solid low-poly flat look
// (soft shadows, pastel palette per theme), camera fits the desk ring, desks are
// clickable (onDeskSelect) with hover tooltips.
import { OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { useEffect, useState } from 'react'
import { useLanguage } from '../../i18n/language-context'
import { AgentDesk } from './agent-desk'
import type { AgentDeskState } from './agent-office-state'
import { CoordinatorDesk } from './coordinator-desk'
import { officeTheme } from './desk-colors'
import { deskPosition, ringRadius } from './desk-layout'
import { OfficeFloor } from './office-floor'
import { OfficeProps } from './office-props'

interface OfficeCanvasProps {
  agentIds: string[]
  desks: Map<string, AgentDeskState>
  // v16: desks render ONLY for CURRENT registry staff (ghost desks from old events are
  // gone); null/undefined = no filtering (callers without a roster yet).
  rosterIds?: string[] | null
  // v16: when a workroom is selected, everyone NOT in it dims — visual only.
  dimmedIds?: Set<string>
  // v32: desk click — the unified screen decides what "open" means (PIC room / agent page).
  onDeskSelect?: (id: string) => void
  // Dual-lens P1 (high-mode only — the unified screen gates it): PIC agents of tasks
  // that have sandbox (needs_shell) steps. Board-API truth, not the event stream.
  needsShellAgents?: Set<string>
  // v54 P4: ✋ pending-count badge, SAME source as the action rail (agent-office-state's
  // derivePendingCounts, computed once in office-unified.tsx) — props-in only, no
  // context inside <Canvas> (r3f rule).
  pendingCounts?: Map<string, number>
}

// Roster filter runs BEFORE ring-index math (red-team m-visibleDesks): positions are
// computed over the VISIBLE list so a filtered-out ghost never leaves a hole in the ring.
export function visibleDesks(agentIds: string[], rosterIds?: string[] | null): string[] {
  if (!rosterIds) return agentIds
  const allowed = new Set(rosterIds)
  return agentIds.filter((id) => allowed.has(id))
}

// v18: the canvas background follows the app theme (the page toggle stamps
// data-theme on <html>) — a MutationObserver keeps it live without a reload.
function useThemeIsDark(): boolean {
  const [dark, setDark] = useState(
    () => document.documentElement.dataset.theme === 'dark',
  )
  useEffect(() => {
    const obs = new MutationObserver(() =>
      setDark(document.documentElement.dataset.theme === 'dark'),
    )
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return dark
}

export function OfficeCanvas({
  agentIds, desks, rosterIds, dimmedIds, onDeskSelect, needsShellAgents, pendingCounts,
}: OfficeCanvasProps) {
  const { t } = useLanguage()
  const visible = visibleDesks(agentIds, rosterIds)
  const dark = useThemeIsDark()
  const theme = officeTheme(dark)
  // Camera fit-to-content: distance scales with the desk ring so 3 desks fill the frame
  // and 15 still fit. Same-count fleets get a stable camera (no jumpiness).
  const radius = ringRadius(visible.length)
  const camY = radius * 1.55
  const camZ = radius * 2.1
  return (
    <div className="office-3d-canvas-wrap">
      <Canvas shadows camera={{ position: [0, camY, camZ], fov: 42 }}>
        <color attach="background" args={[theme.background]} />
        <ambientLight intensity={theme.ambient} />
        <directionalLight
          position={[6, 10, 4]}
          intensity={theme.keyIntensity}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
        />
        <OfficeFloor dark={dark} />
        <OfficeProps />
        <CoordinatorDesk dark={dark} t={t} />
        {visible.map((id, i) => {
          const desk = desks.get(id)
          if (!desk) return null
          const colleagueIdx = desk.consultWith ? visible.indexOf(desk.consultWith) : -1
          const consultPos = colleagueIdx >= 0 ? deskPosition(colleagueIdx, visible.length) : null
          return (
            <AgentDesk
              key={id}
              position={deskPosition(i, visible.length)}
              label={id}
              desk={desk}
              consultPos={consultPos}
              dimmed={dimmedIds?.has(id) ?? false}
              dark={dark}
              onSelect={onDeskSelect}
              needsShell={needsShellAgents?.has(id) ?? false}
              pendingCount={pendingCounts?.get(id) ?? 0}
              t={t}
            />
          )
        })}
        {/* autoRotate = the v14 "living office" slow 360° pan; drei pauses it while the
            user drags and resumes after. Reduced-motion users never reach this component
            — the unified screen renders the 2D table instead. */}
        <OrbitControls
          enablePan={false}
          minDistance={4}
          maxDistance={26}
          autoRotate
          autoRotateSpeed={0.5}
        />
      </Canvas>
    </div>
  )
}

export default OfficeCanvas
