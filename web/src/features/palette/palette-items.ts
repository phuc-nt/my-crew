// What the palette can offer, and how a query narrows it.
//
// Pure: no React, no fetch. Three sources feed the palette and each needs a different
// rule, so the rules live here where they are testable against real strings rather than
// buried in the component's render.
//
//   - navigation  — a fixed list, matched locally, always available offline
//   - command     — the ops catalog (30 entries, fetched once); picking one seeds the
//                   assistant conversation rather than executing anything, because an
//                   ops turn is a sentence the engine parses, not a button
//   - history     — FTS5 hits from /api/search, fetched debounced; matching already
//                   happened server-side so these are never re-filtered here
import type { HistorySearchHit, OpsChatCommand } from '../../types'

export type PaletteKind = 'nav' | 'command' | 'history'

export interface PaletteItem {
  kind: PaletteKind
  /** Stable within a kind; the list key is `${kind}:${id}`. */
  id: string
  label: string
  /** Second line: the command's description, or a hit's agent + time. */
  hint?: string
  /** Where picking it goes. Commands have none — they seed the composer instead. */
  to?: string
}

/** The FTS5 snippet markers. The server wraps matched terms in `»…«`; the palette shows
 *  the excerpt as plain text, so they are stripped rather than rendered literally. */
export function stripHighlights(excerpt: string): string {
  return excerpt.replace(/[»«]/g, '')
}

/** A step hit's ref is "<task_id>:<seq>" — the same address the artifact drawer uses.
 *  Only the task part is a room, so that is what the palette navigates to. */
export function refToRoom(ref: string): string {
  return ref.split(':')[0] ?? ref
}

/**
 * Subsequence match: every character of the query appears in the label, in order.
 * Case-insensitive, spaces ignored, so "vphong" finds "Văn phòng".
 *
 * Diacritics are deliberately NOT normalised. Stripping them would make "cai dat" match
 * "cài đặt", but it would equally make every unaccented query match far more labels, and
 * the palette's nav list is short enough that exact typing is not a burden. History
 * search is the surface for loose queries — that matching is FTS5's job, server-side.
 */
export function fuzzyMatches(query: string, label: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const l = label.toLowerCase()
  let at = 0
  for (const ch of q) {
    if (ch === ' ') continue
    at = l.indexOf(ch, at)
    if (at === -1) return false
    at += 1
  }
  return true
}

export function commandItems(
  commands: readonly OpsChatCommand[],
  query: string,
): PaletteItem[] {
  return commands
    .filter((c) => fuzzyMatches(query, `${c.id} ${c.description}`))
    .map((c) => ({ kind: 'command', id: c.id, label: c.description, hint: c.id }))
}

/**
 * History hits, with a destination only when there is a live one.
 *
 * A step hit's task is USUALLY a workroom, but not always: the FTS5 index reaches
 * further back than the workroom projection, so a real hit can name a room the API now
 * 404s for (measured: task 3e4a8d64ea20 has hits and no room). Linking there would open
 * a permanently empty thread, so a hit whose room is gone stays in the list as readable
 * context with no destination — the excerpt is the answer in that case.
 */
export function historyItems(
  hits: readonly HistorySearchHit[],
  liveRooms: ReadonlySet<string>,
): PaletteItem[] {
  return hits.map((h, i) => {
    const room = refToRoom(h.ref)
    const reachable = h.source === 'step' && liveRooms.has(room)
    return {
      kind: 'history',
      // `ref` can repeat across sources in principle, so the index keeps keys unique.
      id: `${h.ref}#${i}`,
      label: stripHighlights(h.excerpt),
      hint: h.agent_id || h.source,
      ...(reachable ? { to: `/chat/${room}` } : {}),
    }
  })
}
