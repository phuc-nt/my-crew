// The palette's three result sources, merged.
//
// Navigation and commands are matched locally and appear instantly; history is a
// debounced network call, so the list grows under the cursor rather than blocking on it.
// That split is why the sources are merged here and not fetched together: an offline or
// slow search must never delay the palette's ability to navigate.
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { useWorkrooms } from '../../api/queries/use-office-queries'
import type { UiKey } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'
import type { HistorySearchHit, OpsChatCommand } from '../../types'
import { commandItems, fuzzyMatches, historyItems, type PaletteItem } from './palette-items'

/** Below this the history call is not worth making — FTS5 on one character returns
 *  everything, which is the same as returning nothing useful. Matches SearchBox. */
const MIN_QUERY = 2
const DEBOUNCE_MS = 300

const NAV: { key: UiKey; to: string }[] = [
  { key: 'hub.chat', to: '/chat' },
  { key: 'hub.office', to: '/office' },
  { key: 'hub.work', to: '/work' },
  { key: 'hub.team', to: '/team' },
  { key: 'hub.system', to: '/system' },
]

export interface PaletteResults {
  items: PaletteItem[]
  /** True while a history request is in flight, so the list can say so. */
  searching: boolean
}

export function usePaletteResults(query: string): PaletteResults {
  const { t } = useLanguage()
  const [commands, setCommands] = useState<OpsChatCommand[]>([])
  const [hits, setHits] = useState<HistorySearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Already cached by the chat hub, so opening the palette costs no extra request.
  const { data: roomData } = useWorkrooms()

  // Fetched on mount, which is the palette's first open: this hook lives in the lazy
  // overlay chunk, so nothing here runs until the CEO presses the chord.
  useEffect(() => {
    api
      .getOpsChatCommands()
      .then((r) => setCommands(r.commands))
      .catch(() => setCommands([]))
  }, [])

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    const q = query.trim()
    if (q.length < MIN_QUERY) {
      setHits([])
      setSearching(false)
      return
    }
    setSearching(true)
    timer.current = setTimeout(() => {
      api
        .searchHistory(q)
        .then((p) => setHits(p.hits))
        .catch(() => setHits([]))
        .finally(() => setSearching(false))
    }, DEBOUNCE_MS)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [query])

  const liveRooms = useMemo(
    () => new Set((roomData?.rooms ?? []).map((r) => r.room_id)),
    [roomData],
  )

  const items = useMemo(() => {
    const nav: PaletteItem[] = NAV.filter((n) => fuzzyMatches(query, t(n.key))).map((n) => ({
      kind: 'nav',
      id: n.to,
      label: t(n.key),
      to: n.to,
    }))
    return [...nav, ...commandItems(commands, query), ...historyItems(hits, liveRooms)]
  }, [query, commands, hits, liveRooms, t])

  return { items, searching }
}
