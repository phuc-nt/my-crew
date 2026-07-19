// Trigger ops view: a form (kind/audience/dry_run) that POSTs the EXISTING /trigger endpoint,
// then streams the run's live node-progress via the EXISTING SSE stream. The backend validates
// audience + kind strictly (a typo'd value → 422); React mirrors the valid set but the server is
// the authority. v10 M25: the KINDS come from the selected agent's pack (agent.report_kinds),
// not a hardcoded PM four — so an hr/admin agent is offered ITS kinds (red-team F4).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAgent } from '../agent-context'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { PageHeader } from '../components/ui/page-header'
import { useSse } from '../hooks/use-sse'
import { useLanguage } from '../i18n/language-context'
import { AUDIENCE_LABEL, KIND_LABEL, labelFor } from '../labels'

const AUDIENCES = ['internal', 'external']
// Fallback when a payload predates the report_kinds field (older cache): PM's canonical kinds.
const FALLBACK_KINDS = ['daily', 'weekly', 'okr', 'resource']

export function Trigger() {
  const { t } = useLanguage()
  const { selected, agents } = useAgent()
  const kinds = useMemo(() => {
    const a = agents.find((x) => x.id === selected)
    const k = a?.report_kinds
    return k && k.length > 0 ? k : FALLBACK_KINDS
  }, [agents, selected])

  const [kind, setKind] = useState(kinds[0])
  const [audience, setAudience] = useState('internal')
  const [dryRun, setDryRun] = useState(true)
  const [runId, setRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { events, done, errored } = useSse(runId)

  // Keep the selected kind valid when the agent (and thus its kind set) changes.
  useEffect(() => {
    if (!kinds.includes(kind)) setKind(kinds[0])
  }, [kinds, kind])

  const start = useCallback(async () => {
    if (!selected) return
    setBusy(true)
    setError(null)
    setRunId(null)
    try {
      const res = await api.triggerRun(selected, { kind, audience, dry_run: dryRun })
      setRunId(res.run_id)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('trigger.runFailed'))
    } finally {
      setBusy(false)
    }
  }, [selected, kind, audience, dryRun, t])

  return (
    <section>
      <PageHeader title={t('trigger.title')} />
      <div className="trigger-form">
        <label>
          {t('trigger.kindLabel')}{' '}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {labelFor(KIND_LABEL, k, t)}
              </option>
            ))}
          </select>
        </label>{' '}
        <label>
          {t('trigger.audienceLabel')}{' '}
          <select value={audience} onChange={(e) => setAudience(e.target.value)}>
            {AUDIENCES.map((a) => (
              <option key={a} value={a}>
                {labelFor(AUDIENCE_LABEL, a, t)}
              </option>
            ))}
          </select>
        </label>{' '}
        <label>
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />{' '}
          {t('trigger.dryRun')}
        </label>{' '}
        <Button variant="ghost" disabled={busy || !selected} onClick={start}>
          {busy ? t('trigger.running') : t('trigger.run')}
        </Button>
      </div>
      {error && <p className="error">{t('trigger.errorPrefix', { message: error })}</p>}
      {runId && (
        <div className="run-stream">
          <h3>
            {t('trigger.runTitle', {
              runId,
              status: errored
                ? t('trigger.statusDisconnected')
                : done
                  ? t('trigger.statusDone')
                  : t('trigger.statusRunning'),
            })}
          </h3>
          {errored && (
            <p className="error">{t('trigger.streamDisconnected')}</p>
          )}
          <ul>
            {events.map((ev, i) => (
              <li key={i}>
                {ev.event === 'node'
                  ? `${ev.node}: ${JSON.stringify(ev.data)}`
                  : `${t('trigger.eventDone')} · ${ev.status} ${JSON.stringify(ev.data)}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
