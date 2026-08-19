// "Chạy ngay" — the run trigger lifted out of the old Trigger.tsx corner and put next to
// the agent it runs. One button, live progress underneath, no parameters: the parameterised
// form still exists behind the detail page's 🔬 Nâng cao tab for the cases that need it.
//
// The backend drains a run's event stream ONCE. A second EventSource on the same run id
// gets a 409, so the button stays locked from the click until the stream terminates —
// the lock is the reason this is a component and not two lines inside the roster row.
import { useState } from 'react'
import { ApiError, api } from '../../api/client'
import { Button } from '../../components/ui/button'
import { useSse } from '../../hooks/use-sse'
import { useLanguage } from '../../i18n/language-context'
import type { AgentSummary } from '../../types'

/** Kinds predate `report_kinds` in some registries; fall back to the PM set. */
const FALLBACK_KIND = 'daily'

export function RunNowButton({ agent }: { agent: AgentSummary }) {
  const { t } = useLanguage()
  const [runId, setRunId] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { events, done, errored } = useSse(runId)

  // Locked while starting AND while a stream is still open — the whole point of the lock.
  const locked = starting || (runId !== null && !done)

  async function start() {
    setStarting(true)
    setError(null)
    setRunId(null)
    try {
      const kind = agent.report_kinds?.[0] ?? FALLBACK_KIND
      const out = await api.triggerRun(agent.id, { kind, audience: 'internal', dry_run: false })
      setRunId(out.run_id)
    } catch (e) {
      // A 409 is not a failure — the backend already has a run in flight for this agent
      // (started here, from another tab, or by the scheduler). Saying so in the user's
      // language beats surfacing the backend's raw English, and re-arming the button would
      // only earn another 409 on the next click.
      setError(
        e instanceof ApiError && e.status === 409 ? t('runNow.alreadyRunning') : t('runNow.failed'),
      )
    } finally {
      setStarting(false)
    }
  }

  const last = events[events.length - 1]
  return (
    <span className="run-now">
      <Button
        variant="chip"
        disabled={locked}
        title={locked ? t('runNow.lockedHint') : undefined}
        onClick={() => void start()}
      >
        {locked ? t('runNow.running') : t('runNow.label')}
      </Button>
      {error && <span className="error"> {error}</span>}
      {runId && (
        <span className="run-now-progress muted">
          {' '}
          {errored
            ? t('runNow.disconnected')
            : done
              ? t('runNow.done')
              : (last?.node ?? t('runNow.starting'))}
        </span>
      )}
    </span>
  )
}
