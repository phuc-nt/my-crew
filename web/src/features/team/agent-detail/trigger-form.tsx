// The parameterised run trigger, ported from the old /trigger route. Kinds are per-agent
// (`report_kinds`); the server is the authority and 422s an unknown one, so the form only
// mirrors the valid set. The stream distinguishes "finished" from "dropped" — a dropped
// connection rendering as "(done)" was a silent lie the old view had to fix.
import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { Button } from '../../../components/ui/button'
import { useSse } from '../../../hooks/use-sse'
import { useLanguage } from '../../../i18n/language-context'
import { AUDIENCE_LABEL, KIND_LABEL, labelFor } from '../../../labels'

/** Registries predating `report_kinds` fall back to the PM set. */
const FALLBACK_KINDS = ['daily', 'weekly', 'okr', 'resource']

export function TriggerForm({ id, kinds }: { id: string; kinds?: string[] }) {
  const { t } = useLanguage()
  const available = kinds && kinds.length > 0 ? kinds : FALLBACK_KINDS
  const [kind, setKind] = useState(available[0])
  const [audience, setAudience] = useState('internal')
  const [dryRun, setDryRun] = useState(true)
  const [runId, setRunId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { events, done, errored } = useSse(runId)

  // Switching agents can invalidate the selected kind; reset rather than POST a 422.
  useEffect(() => {
    if (!available.includes(kind)) setKind(available[0])
  }, [available, kind])

  async function start() {
    setBusy(true)
    setError(null)
    setRunId(null) // a new run resets the stream instead of appending to the old one
    try {
      const out = await api.triggerRun(id, { kind, audience, dry_run: dryRun })
      setRunId(out.run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('runNow.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="trigger-form">
      <label>
        {t('trigger.kindLabel')}
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {available.map((k) => (
            <option key={k} value={k}>
              {labelFor(KIND_LABEL, k, t)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t('trigger.audienceLabel')}
        <select value={audience} onChange={(e) => setAudience(e.target.value)}>
          <option value="internal">{labelFor(AUDIENCE_LABEL, 'internal', t)}</option>
          <option value="external">{labelFor(AUDIENCE_LABEL, 'external', t)}</option>
        </select>
      </label>
      <label>
        <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
        {t('trigger.dryRun')}
      </label>
      {/* Locked while a stream is open: the backend drains a run once, so a second
          EventSource on the same run gets a 409. */}
      <Button variant="primary" disabled={busy || (runId !== null && !done)} onClick={() => void start()}>
        {t('trigger.run')}
      </Button>
      {error && <p className="error">{error}</p>}
      {runId && (
        <div className="run-stream">
          <h5>
            {runId} —{' '}
            {errored ? t('runNow.disconnected') : done ? t('runNow.done') : t('runNow.running')}
          </h5>
          {errored && <p className="error">{t('trigger.streamDisconnected')}</p>}
          <ul>
            {events.map((e, i) => (
              <li key={i}>
                {e.node ?? e.event} {e.status ? `· ${e.status}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
