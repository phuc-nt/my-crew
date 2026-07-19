// A single agent's desk + mini avatar (v32 solid low-poly flat). The STATE hue now
// lives on the monitor screen + a status pill above the desk (was: wireframe desk
// outline); the avatar keeps the agent's PERSONAL hue + one accessory (nón / kính /
// cà vạt, picked deterministically from the agent id). All movement contracts are
// unchanged from v14/v15: the avatar tweens to the desk on `assigned`, to the meeting
// point while `consultWith` is set, a thicker/brighter pill marks `done`, and the idle
// breathing bob stays cosmetic-only (same amplitude in every state).
//
// v32 interaction: the whole desk group is clickable (an invisible hitbox LARGER than
// the meshes so wireframe-thin parts aren't a miss) and hover shows a tooltip with the
// live state — both wired through props so the fallback table offers the same actions.
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import type { UiKey } from '../../i18n/dictionary'
import { DICT } from '../../i18n/dictionary'
import { shouldShowBubble } from './agent-office-state'
import type { AgentDeskState } from './agent-office-state'
import { DeepTeamGhost, DeskStatusBadges } from './desk-badges'
import { DESK_EDGE_COLOR, VERDICT_FLASH_COLOR, agentColor, agentHash, officeTheme } from './desk-colors'
import { consultMeetPoint } from './desk-layout'
import { SpeechBubble } from './speech-bubble'

// Avatar rest spot: just behind the desk when idle/waiting, "at desk" when assigned/working.
const AVATAR_REST_OFFSET: [number, number, number] = [0, 0, 1.4]
const AVATAR_DESK_OFFSET: [number, number, number] = [0, 0, 0.62]
const TWEEN_SPEED = 2.5 // lerp factor — reaches the desk in well under a second
const BOB_AMPLITUDE = 0.015 // breathing bob (cosmetic only — see file header)
const BOB_SPEED = 1.6

interface AgentDeskProps {
  position: [number, number, number]
  label: string
  desk: AgentDeskState
  dimmed?: boolean
  consultPos: [number, number, number] | null
  dark?: boolean
  // v32: desk click → the unified screen decides (open PIC room / agent page).
  onSelect?: (id: string) => void
  // Dual-lens P1 (high-mode only — parent gates it): this agent is PIC of a task with
  // sandbox (needs_shell) steps. Task-level truth from the board API, not the stream.
  needsShell?: boolean
  // v54 P4: ✋ pending-count badge — SAME source as the action rail (derivePendingCounts
  // in agent-office-state.ts, computed once in office-unified.tsx and threaded down
  // through OfficeCanvas so there is exactly one poll, not a second one per desk).
  pendingCount?: number
  // v53 i18n: this component renders inside <Canvas> (react-three-fiber), so it cannot
  // call useLanguage() itself — the translate function is threaded down as a prop from
  // office-unified.tsx via OfficeCanvas.
  t: (key: UiKey, params?: Record<string, string | number>) => string
}

// Verdict flash lifetime — render-side fade keyed off the EVENT timestamp, so an SSE
// reconnect-replay of an old review never re-flashes (the reducer stays pure).
const VERDICT_FLASH_MS = 3000

// One solid low-poly person: head + capsule body in the agent's personal hue + accessory.
function AgentAvatar({ id, skin }: { id: string; skin: string }) {
  const color = agentColor(id)
  const accessory = agentHash(id) % 3
  return (
    <group>
      <mesh position={[0, 0.42, 0]} castShadow>
        <capsuleGeometry args={[0.19, 0.34, 4, 8]} />
        <meshLambertMaterial color={color} />
      </mesh>
      <mesh position={[0, 0.88, 0]} castShadow>
        <sphereGeometry args={[0.16, 16, 12]} />
        <meshLambertMaterial color={skin} />
      </mesh>
      {accessory === 0 && (
        <mesh position={[0, 1.06, 0]} castShadow>
          <coneGeometry args={[0.19, 0.16, 8]} />
          <meshLambertMaterial color={color} />
        </mesh>
      )}
      {accessory === 1 && (
        <mesh position={[0, 0.9, 0.14]}>
          <boxGeometry args={[0.28, 0.07, 0.05]} />
          <meshLambertMaterial color="#334155" />
        </mesh>
      )}
      {accessory === 2 && (
        <mesh position={[0, 0.52, 0.19]}>
          <boxGeometry args={[0.08, 0.24, 0.03]} />
          <meshLambertMaterial color="#c0392b" />
        </mesh>
      )}
    </group>
  )
}

// One-liner for the tooltip — mirrors the fallback table's state labels. `t` is optional
// so existing callers/tests that only need the vi-default text (module-level constant,
// no language context available) can omit it — it falls back to DICT.vi directly.
export function deskTooltipText(
  desk: AgentDeskState,
  t?: (key: UiKey, params?: Record<string, string | number>) => string,
): string {
  const tr = t ?? ((key: UiKey) => DICT.vi[key])
  const state =
    desk.state === 'working' ? tr('agentDesk.stateWorking') :
    desk.state === 'assigned' ? tr('agentDesk.stateAssigned') :
    desk.state === 'done' ? tr('agentDesk.stateDone') :
    desk.state === 'error' ? tr('agentDesk.stateError') : tr('agentDesk.stateIdle')
  const doing = desk.stepTitle || desk.taskTitle
  return doing ? `${state} — ${doing}` : state
}

// Age-based flash opacity [0..1]; exported for unit tests (pure, no Fiber needed).
// Slight client-behind-server clock skew yields a small negative age — clamp to 0
// (full flash) instead of suppressing the flash entirely (review Low#2).
export function verdictFlashStrength(ts: string, now: number): number {
  const age = Math.max(0, now - Date.parse(ts))
  if (!Number.isFinite(age) || age >= VERDICT_FLASH_MS) return 0
  return 1 - age / VERDICT_FLASH_MS
}

export function AgentDesk({
  position, label, desk, consultPos, dimmed, dark, onSelect, needsShell, pendingCount, t,
}: AgentDeskProps) {
  const avatarRef = useRef<THREE.Group>(null)
  const bobRef = useRef<THREE.Group>(null) // inner group: bob rides here, NOT inside the lerp
  const screenMatRef = useRef<THREE.MeshBasicMaterial>(null) // error pulse rides the screen
  const flashMatRef = useRef<THREE.MeshBasicMaterial>(null) // verdict flash ring
  const [hovered, setHovered] = useState(false)
  // Unmounting while hovered (roster shrink, fallback flip, navigating away from the
  // desk's own click) must not leave the page stuck with a pointer cursor.
  useEffect(() => () => {
    document.body.style.cursor = 'default'
  }, [])
  const theme = officeTheme(dark ?? false)
  const bobPhase = agentHash(label) % 7 // de-sync the bobs so the room doesn't pulse in unison
  const deskOffset =
    desk.state === 'assigned' || desk.state === 'working' || desk.state === 'done'
      ? AVATAR_DESK_OFFSET
      : AVATAR_REST_OFFSET
  const target: [number, number, number] = consultPos
    ? consultMeetPoint(position, consultPos)
    : [
        position[0] + deskOffset[0],
        position[1] + deskOffset[1],
        position[2] + deskOffset[2],
      ]

  useFrame((state, delta) => {
    const avatar = avatarRef.current
    if (!avatar) return
    const t = Math.min(1, delta * TWEEN_SPEED)
    avatar.position.x += (target[0] - avatar.position.x) * t
    avatar.position.y += (target[1] - avatar.position.y) * t
    avatar.position.z += (target[2] - avatar.position.z) * t
    const bob = bobRef.current
    if (bob) {
      bob.position.y = BOB_AMPLITUDE * Math.sin(state.clock.elapsedTime * BOB_SPEED + bobPhase)
    }
    const [faceX, faceZ] = consultPos ? [consultPos[0], consultPos[2]] : [0, 0]
    const angle = Math.atan2(faceX - avatar.position.x, faceZ - avatar.position.z)
    const rawTurn = angle - avatar.rotation.y
    const shortTurn = Math.atan2(Math.sin(rawTurn), Math.cos(rawTurn))
    avatar.rotation.y += shortTurn * t
    // Dual-lens P1: error pulse (screen opacity breathes hard) + verdict flash decay.
    const screenMat = screenMatRef.current
    if (screenMat) {
      screenMat.opacity =
        desk.state === 'error'
          ? 0.55 + 0.45 * Math.sin(state.clock.elapsedTime * 6)
          : desk.state === 'idle' ? 0.35 : 1
    }
    const flashMat = flashMatRef.current
    if (flashMat && desk.lastVerdict) {
      flashMat.opacity = 0.85 * verdictFlashStrength(desk.lastVerdict.ts, Date.now())
    }
  })

  const stateColor = DESK_EDGE_COLOR[desk.state]
  const bubblePosition: [number, number, number] = [position[0], position[1] + 1.9, position[2]]

  return (
    <group scale={dimmed ? 0.65 : 1}>
      <group position={position}>
        {/* invisible hitbox covering desk + seated avatar — the click/hover surface */}
        <mesh
          position={[0, 0.7, 0.3]}
          onClick={(e) => {
            e.stopPropagation()
            onSelect?.(label)
          }}
          onPointerOver={(e) => {
            e.stopPropagation()
            setHovered(true)
            document.body.style.cursor = onSelect ? 'pointer' : 'default'
          }}
          onPointerOut={() => {
            setHovered(false)
            document.body.style.cursor = 'default'
          }}
        >
          <boxGeometry args={[2.2, 1.7, 2.4]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
        {/* desk: light top + panel legs */}
        <mesh position={[0, 0.72, 0]} castShadow>
          <boxGeometry args={[1.9, 0.14, 1.0]} />
          <meshLambertMaterial color={theme.deskTop} />
        </mesh>
        {[-0.8, 0.8].map((x) => (
          <mesh key={x} position={[x, 0.36, 0]}>
            <boxGeometry args={[0.1, 0.72, 0.9]} />
            <meshLambertMaterial color={theme.deskLeg} />
          </mesh>
        ))}
        {/* monitor: bezel + STATE-colored screen (the "what is happening" surface) */}
        <mesh position={[0, 1.12, -0.28]} castShadow>
          <boxGeometry args={[0.72, 0.45, 0.06]} />
          <meshLambertMaterial color={theme.monitor} />
        </mesh>
        <mesh position={[0, 1.12, -0.246]}>
          <planeGeometry args={[0.62, 0.36]} />
          <meshBasicMaterial
            ref={screenMatRef}
            color={stateColor}
            transparent
            opacity={desk.state === 'idle' ? 0.35 : 1}
          />
        </mesh>
        {/* verdict flash ring on the floor — green (passed) / orange (needs_rework),
            fades over VERDICT_FLASH_MS keyed to the event timestamp (no re-flash on
            SSE replay). Rendered only while a verdict is fresh enough to matter. */}
        {desk.lastVerdict &&
          verdictFlashStrength(desk.lastVerdict.ts, Date.now()) > 0 && (
            <mesh position={[0, 0.03, 0.35]} rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[0.9, 1.15, 32]} />
              <meshBasicMaterial
                ref={flashMatRef}
                color={VERDICT_FLASH_COLOR[desk.lastVerdict.verdict]}
                transparent
                opacity={0.85}
                depthWrite={false}
              />
            </mesh>
          )}
        {/* status pill above the desk corner — thicker on `done` (the old outline cue) */}
        <mesh position={[0.75, 1.5, 0]} scale={desk.state === 'done' ? 1.4 : 1}>
          <sphereGeometry args={[0.1, 16, 12]} />
          <meshBasicMaterial color={stateColor} />
        </mesh>
        {hovered && (
          <Html position={[0, 2.2, 0]} center distanceFactor={9} occlude={false}>
            <div className="office-3d-tooltip">
              <strong>{label}</strong> · {deskTooltipText(desk, t)}
              {onSelect && <div className="muted">{t('agentDesk.clickToOpen')}</div>}
            </div>
          </Html>
        )}
      </group>
      <group
        ref={avatarRef}
        position={[
          position[0] + AVATAR_REST_OFFSET[0],
          position[1] + AVATAR_REST_OFFSET[1],
          position[2] + AVATAR_REST_OFFSET[2],
        ]}
      >
        <group ref={bobRef}>
          <AgentAvatar id={label} skin={theme.skin} />
          {/* v54 P4: deep_team ghost sits just beside the avatar's own body, inside the
              SAME lerp/bob group so it moves with the desk↔consult tween for free
              (no separate useFrame) — static offset, no independent animation. */}
          {desk.deepTeamActive && (
            <DeepTeamGhost position={[0.35, 0, 0]} color={agentColor(label)} skin={theme.skin} />
          )}
        </group>
      </group>
      <DeskStatusBadges
        position={[position[0], position[1] + 2.05, position[2]]}
        pendingCount={pendingCount ?? 0}
        concurrentSteps={desk.concurrentSteps}
        t={t}
      />
      <Html position={[position[0], position[1] + 1.7, position[2]]} center distanceFactor={10} occlude={false}>
        <div className="office-3d-label" style={{ color: agentColor(label) }}>
          {desk.picTasks.size > 0 ? '⭐ ' : ''}
          {needsShell ? '🔒 ' : ''}
          {label}
        </div>
      </Html>
      {shouldShowBubble(desk) && (
        <SpeechBubble
          position={bubblePosition}
          taskTitle={desk.taskTitle}
          stepTitle={desk.stepTitle}
          phase={desk.phase}
          consultWith={desk.consultWith}
          isPic={desk.picTasks.size > 0}
          isError={desk.state === 'error'}
          t={t}
        />
      )}
    </group>
  )
}
