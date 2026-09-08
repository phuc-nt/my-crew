// v96: what the palette offers "Ở đây" — the actions that belong to the hub the CEO is
// standing in, listed first. Pure: the route is a string in, items out, so the map
// from route to actions is testable without a router.
import { ASSISTANT_CONVERSATION_ID } from '../chat/conversation-list-state'
import type { UiKey } from '../../i18n/dictionary'
import { fuzzyMatches, type PaletteItem } from './palette-items'

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

interface ContextEntry {
  id: string
  labelKey: UiKey
  to: string
}

const WORK_TABS: ContextEntry[] = [
  { id: 'work-board', labelKey: 'workHub.tabBoard', to: '/work?tab=board' },
  { id: 'work-outputs', labelKey: 'workHub.tabOutputs', to: '/work?tab=outputs' },
  { id: 'work-schedule', labelKey: 'workHub.tabSchedule', to: '/work?tab=schedule' },
  { id: 'work-activity', labelKey: 'workHub.tabActivity', to: '/work?tab=activity' },
]

const SYSTEM_TABS: ContextEntry[] = [
  { id: 'system-settings', labelKey: 'systemHub.tabSettings', to: '/system?tab=settings' },
  { id: 'system-connections', labelKey: 'systemHub.tabConnections', to: '/system?tab=connections' },
  { id: 'system-company', labelKey: 'systemHub.tabCompany', to: '/system?tab=company' },
  { id: 'system-insights', labelKey: 'systemHub.tabInsights', to: '/system?tab=insights' },
  { id: 'system-audit', labelKey: 'systemHub.tabAudit', to: '/system?tab=audit' },
]

const NEW_BRIEF: ContextEntry = { id: 'new-brief', labelKey: 'palette.ctx.newBrief', to: '/chat' }
const ASK_ASSISTANT: ContextEntry = {
  id: 'ask-assistant',
  labelKey: 'palette.ctx.askAssistant',
  to: `/chat/${ASSISTANT_CONVERSATION_ID}`,
}
const CREATE_AGENT: ContextEntry = {
  id: 'create-agent',
  labelKey: 'palette.ctx.createAgent',
  to: '/team?hire=1',
}

/** The chat room in `/chat/<room>`, or null on the overview and assistant threads. */
export function chatRoomOf(pathname: string): string | null {
  const m = /^\/chat\/([^/]+)$/.exec(pathname)
  if (!m) return null
  const room = decodeURIComponent(m[1])
  return room === ASSISTANT_CONVERSATION_ID ? null : room
}

function entriesFor(pathname: string): ContextEntry[] {
  if (pathname === '/chat' || pathname.startsWith('/chat/')) {
    const room = chatRoomOf(pathname)
    const here: ContextEntry[] = [NEW_BRIEF, ASK_ASSISTANT]
    if (room) {
      here.push({
        id: `task-${room}`,
        labelKey: 'palette.ctx.taskDetail',
        to: `/work/task/${encodeURIComponent(room)}`,
      })
    }
    return here
  }
  if (pathname === '/work' || pathname.startsWith('/work/')) return [...WORK_TABS, NEW_BRIEF]
  if (pathname === '/team' || pathname.startsWith('/team/')) return [CREATE_AGENT, ASK_ASSISTANT]
  if (pathname === '/system' || pathname.startsWith('/system/')) return SYSTEM_TABS
  if (pathname === '/office') return [NEW_BRIEF, WORK_TABS[0]]
  return []
}

export function contextualCommands(pathname: string, query: string, t: Translate): PaletteItem[] {
  const here = t('palette.here')
  return entriesFor(pathname)
    .map((e) => ({ kind: 'context' as const, id: e.id, label: t(e.labelKey), hint: here, to: e.to }))
    .filter((item) => fuzzyMatches(query, item.label))
}
