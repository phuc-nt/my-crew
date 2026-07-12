// Palette for the 3D office (v32 "đại tu visual": solid low-poly flat, CEO decision —
// replaces the v12-v31 translucent wireframe look). Two readable dimensions stay the
// contract: WHO = the avatar's personal hue (stable per agent id), WHAT STATE = the
// status hue on the monitor screen + status pill (was: desk outline).
//
// three.js materials can't resolve CSS custom properties, so the theme rides in as a
// boolean (`officeTheme(dark)`) with two hand-tuned palettes — same pattern the floor
// used since v18, now centralized here for every solid mesh.
import type { AgentState } from './agent-office-state'

// State hues (monitor screen + status pill). Bright enough for both themes — they sit
// on dark monitor bezels / above desks, not on the floor.
export const DESK_EDGE_COLOR: Record<AgentState, string> = {
  idle: '#94a3b8', // neutral slate — waiting, no task
  assigned: '#3b82f6', // accent blue — task received, walking to desk
  working: '#f59e0b', // amber — actively working
  done: '#34d399', // green — step completed
}

export const COORDINATOR_EDGE_COLOR = '#38506e' // deep slate-blue — distinct, always visible

// Personality palette: each agent keeps a stable personal hue (avatar body), independent
// of the state hue. Softened for solid (Lambert) bodies on the pastel floor.
const AGENT_PALETTE = [
  '#e06c6c', // đỏ gạch
  '#5b8def', // xanh dương
  '#3fae72', // xanh lá
  '#c86db8', // hồng tím
  '#e89a4b', // cam đất
  '#3fa9a9', // teal
  '#8f7ae0', // tím
  '#b08a3e', // nâu vàng
]

export function agentHash(id: string): number {
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h
}

export function agentColor(id: string): string {
  return AGENT_PALETTE[agentHash(id) % AGENT_PALETTE.length]
}

// Solid-scene palette per theme. Light = the mockup's pastel daylight office; dark = the
// same furniture in a dimmed room (furniture stays light so silhouettes read; floor and
// background drop toward the app's dark tokens).
export interface OfficeTheme {
  background: string
  floor: string
  rug: string
  deskTop: string
  deskLeg: string
  monitor: string
  skin: string
  tableTop: string
  tableLeg: string
  ambient: number
  keyIntensity: number
}

export function officeTheme(dark: boolean): OfficeTheme {
  return dark
    ? {
        background: '#171a20',
        floor: '#232936',
        rug: '#2e3a52',
        deskTop: '#cfd8e6',
        deskLeg: '#5d6b80',
        monitor: '#334155',
        skin: '#f2c9a0',
        tableTop: '#d8c49c',
        tableLeg: '#a08a5e',
        ambient: 0.7,
        keyIntensity: 1.1,
      }
    : {
        background: '#eef2f7',
        floor: '#dde5ef',
        rug: '#c7d8f0',
        deskTop: '#f8fafc',
        deskLeg: '#b8c4d4',
        monitor: '#475569',
        skin: '#ffd9b3',
        tableTop: '#f8e8c8',
        tableLeg: '#d9c49a',
        ambient: 1.1,
        keyIntensity: 1.6,
      }
}
