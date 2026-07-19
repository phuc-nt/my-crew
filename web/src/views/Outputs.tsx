// v33 P3: "Kết quả" — the cross-room outputs hub. One flat, filterable list of every
// delivered step artifact + every exported file, newest first. A step row opens the
// same ArtifactViewer the office uses; a file row downloads through the confined
// endpoint. Read-only by design.
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { formatDateTime } from '../labels'
import { ArtifactViewer } from './office-unified/artifact-viewer'
import type { OutputItem } from '../types'

function fmtTs(ts: string): string {
  return formatDateTime(ts) || ts
}

export function Outputs() {
  const { t } = useLanguage()
  const [items, setItems] = useState<OutputItem[]>([])
  const [truncated, setTruncated] = useState(false)
  const [agent, setAgent] = useState('')
  const [days, setDays] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openStep, setOpenStep] = useState<OutputItem | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api
      .getOutputs(agent || undefined, days || undefined)
      .then((res) => {
        setItems(res.items)
        setTruncated(res.truncated)
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : t('outputs.loadError')),
      )
      .finally(() => setLoading(false))
  }, [agent, days, t])

  // Agent filter options come from the loaded rows themselves — no extra fetch, and
  // the list only offers agents that actually produced something.
  const agents = useMemo(
    () => [...new Set(items.map((i) => i.agent_id).filter(Boolean))].sort(),
    [items],
  )

  return (
    <section className="outputs-page">
      <PageHeader title={t('outputs.title')} />
      <p className="muted">
        {t('outputs.introPrefix')}
        <Link to="/office">{t('outputs.introLink')}</Link>
        {t('outputs.introSuffix')}
      </p>

      <div className="outputs-filters">
        <label>
          {t('outputs.filterAgent')}{' '}
          <select value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">{t('outputs.filterAll')}</option>
            {agents.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t('outputs.filterTime')}{' '}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={0}>{t('outputs.timeAll')}</option>
            <option value={7}>{t('outputs.time7d')}</option>
            <option value={30}>{t('outputs.time30d')}</option>
          </select>
        </label>
      </div>

      {loading && <p className="muted">{t('outputs.loading')}</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <EmptyState>{t('outputs.empty')}</EmptyState>
      )}

      <ul className="outputs-list">
        {items.map((item) =>
          item.kind === 'step' ? (
            <li key={`s-${item.task_id}-${item.seq}`} className="outputs-row">
              <button type="button" className="outputs-open" onClick={() => setOpenStep(item)}>
                <span className="outputs-title">{item.step_title}</span>
                <span className="muted"> — {item.task_title}</span>
              </button>
              <span className="outputs-meta">
                <span className="outputs-agent">{item.agent_id}</span>
                <span className="muted">{fmtTs(item.ts)}</span>
              </span>
            </li>
          ) : (
            <li key={`f-${item.agent_id}-${item.name}`} className="outputs-row">
              <a
                className="outputs-open"
                href={`/api/outputs/file/${encodeURIComponent(item.agent_id)}/${encodeURIComponent(item.name ?? '')}`}
              >
                <span className="outputs-title">📎 {item.name}</span>
                <span className="muted"> — {t('outputs.fileExport')}</span>
              </a>
              <span className="outputs-meta">
                <span className="outputs-agent">{item.agent_id}</span>
                <span className="muted">{fmtTs(item.ts)}</span>
              </span>
            </li>
          ),
        )}
      </ul>
      {truncated && <p className="muted">{t('outputs.truncated')}</p>}

      {openStep && (
        <ArtifactViewer
          taskId={openStep.task_id}
          seq={openStep.seq}
          stepId={`seq-${openStep.seq}`}
          onClose={() => setOpenStep(null)}
        />
      )}
    </section>
  )
}
