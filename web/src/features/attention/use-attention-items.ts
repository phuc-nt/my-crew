// Feeds the attention center from the query cache. Every source is a key some hub
// already subscribes to (approvals, clarify, board, budget, alerts, template status,
// coordinator health), so mounting this in the shell adds no new polling: the SSE
// bridge and the existing staleTimes keep the list current.
import { useCallback, useMemo, useState } from 'react'
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

export interface AttentionState {
  /** Visible (not dismissed) items, most severe first. */
  items: AttentionItem[]
  /** Bell badge: errors + warnings. Info rows never count. */
  badge: number
  /** How many current items are hidden by a dismissal. */
  hidden: number
  dismiss: (item: AttentionItem) => void
  dismissAll: () => void
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

  const items = useMemo(() => all.filter((i) => !isDismissed(i, dismissed)), [all, dismissed])

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

  return {
    items,
    badge: items.filter((i) => i.severity !== 'info').length,
    hidden: all.length - items.length,
    dismiss,
    dismissAll,
  }
}
