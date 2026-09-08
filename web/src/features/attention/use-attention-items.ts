// Feeds the attention center from the query cache. Every source is a key some hub
// already subscribes to (approvals, clarify, board, budget, alerts, template status,
// coordinator health), so mounting this in the shell adds no new polling: the SSE
// bridge and the existing staleTimes keep the list current.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePendingApprovals } from '../../api/queries/use-approvals-queries'
import { usePendingClarify } from '../../api/queries/use-clarify-queries'
import { useCoordinatorHealth, useFleetBudget } from '../../api/queries/use-system-queries'
import { useTeamAlerts, useTemplateStatus } from '../../api/queries/use-team-queries'
import { useTaskBoard } from '../../api/queries/use-work-queries'
import { useLanguage } from '../../i18n/language-context'
import {
  buildAttentionItems,
  isDismissed,
  readDismissed,
  writeDismissed,
  type AttentionItem,
  type DismissedMap,
} from './attention-items'
import {
  isSnoozed,
  nextSnoozeExpiry,
  readSnoozed,
  withSnooze,
  writeSnoozed,
  type SnoozedMap,
} from './snooze'

export interface AttentionState {
  /** Visible (neither dismissed nor snoozed) items, most severe first. */
  items: AttentionItem[]
  /** Bell badge: errors + warnings. Info rows never count. */
  badge: number
  /** How many current items are hidden by a dismissal. */
  hidden: number
  /** How many current items are hidden by a running snooze. */
  snoozed: number
  dismiss: (item: AttentionItem) => void
  dismissAll: () => void
  /** v96: hide the row until `durationMs` from now; it comes back on its own. */
  snooze: (item: AttentionItem, durationMs: number) => void
}

export function useAttentionItems(): AttentionState {
  const { t } = useLanguage()
  const { data: approvals } = usePendingApprovals()
  const { data: clarify } = usePendingClarify()
  const { data: board } = useTaskBoard()
  const { data: budget } = useFleetBudget()
  const { data: coordinator } = useCoordinatorHealth()
  const { data: alerts } = useTeamAlerts()
  const { data: templates } = useTemplateStatus()
  const [dismissed, setDismissed] = useState<DismissedMap>(readDismissed)
  const [snoozedMap, setSnoozedMap] = useState<SnoozedMap>(() => readSnoozed())
  // The clock the snooze filter reads. Bumped by a timer armed for the earliest
  // deadline, so a snoozed row reappears without a reload and without polling.
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const next = nextSnoozeExpiry(snoozedMap, now)
    if (next === null) return
    const timer = setTimeout(() => setNow(Date.now()), Math.max(0, next - now) + 50)
    return () => clearTimeout(timer)
  }, [snoozedMap, now])

  const all = useMemo(
    () =>
      buildAttentionItems(
        {
          approvals: approvals?.pending,
          clarify: clarify?.questions,
          lanes: board?.lanes,
          budget,
          coordinator,
          alerts: alerts?.alerts,
          templates: templates?.agents,
        },
        t,
      ),
    [approvals, clarify, board, budget, coordinator, alerts, templates, t],
  )

  const { items, hidden, snoozed } = useMemo(() => {
    const visible: AttentionItem[] = []
    let hiddenCount = 0
    let snoozedCount = 0
    for (const item of all) {
      if (isDismissed(item, dismissed)) hiddenCount += 1
      else if (isSnoozed(item, snoozedMap, now)) snoozedCount += 1
      else visible.push(item)
    }
    return { items: visible, hidden: hiddenCount, snoozed: snoozedCount }
  }, [all, dismissed, snoozedMap, now])

  const persist = useCallback((next: DismissedMap) => {
    setDismissed(next)
    writeDismissed(next)
  }, [])

  const dismiss = useCallback(
    (item: AttentionItem) => persist({ ...dismissed, [item.id]: item.fingerprint }),
    [dismissed, persist],
  )

  // Also the pruning point: entries for items that no longer exist are dropped, so the
  // map never grows past the fleet's current signal count.
  const dismissAll = useCallback(() => {
    const next: DismissedMap = {}
    for (const i of all) next[i.id] = i.fingerprint
    persist(next)
  }, [all, persist])

  const snooze = useCallback(
    (item: AttentionItem, durationMs: number) => {
      const at = Date.now()
      const next = withSnooze(snoozedMap, item, durationMs, at)
      setSnoozedMap(next)
      setNow(at)
      writeSnoozed(next)
    },
    [snoozedMap],
  )

  return {
    items,
    badge: items.filter((i) => i.severity !== 'info').length,
    hidden,
    snoozed,
    dismiss,
    dismissAll,
    snooze,
  }
}
