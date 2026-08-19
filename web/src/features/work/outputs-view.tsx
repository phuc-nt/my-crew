// "Kết quả" — every delivered step artifact and exported file, newest first.
//
// Same data as the old Outputs page, but on the shared query key so the SSE bridge
// refreshes it when a step delivers instead of it going stale until a remount. A step
// row opens the same StepArtifactView the chat drawer uses (one renderer, one 🔬).
import { useMemo, useState } from 'react'
import { useOutputs } from '../../api/queries/use-work-queries'
import { EmptyState } from '../../components/ui/empty-state'
import { StepArtifactView } from '../chat/artifacts/step-artifact-view'
import { useLanguage } from '../../i18n/language-context'
import { formatDateTime } from '../../labels'
import type { OutputItem } from '../../types'

export function OutputsView() {
  const { t } = useLanguage()
  const [agent, setAgent] = useState('')
  const [days, setDays] = useState(0)
  const [openStep, setOpenStep] = useState<OutputItem | null>(null)
  const { data, isLoading, isError } = useOutputs(agent, days)

  const items = useMemo(() => data?.items ?? [], [data])
  // Options come from the loaded rows, so the filter only offers agents that produced
  // something. Narrowing the filter narrows the options too, which is why the "all"
  // entry always stays: it is the only way back to the full list.
  const agents = useMemo(
    () => [...new Set(items.map((i) => i.agent_id).filter(Boolean))].sort(),
    [items],
  )

  return (
    <section className="outputs-view">
      <div className="board-filters">
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

      {isLoading && <p className="muted">{t('outputs.loading')}</p>}
      {isError && <p className="error">{t('outputs.loadError')}</p>}
      {!isLoading && !isError && items.length === 0 && <EmptyState>{t('outputs.empty')}</EmptyState>}

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
                <span className="muted">{formatDateTime(item.ts) || item.ts}</span>
              </span>
            </li>
          ) : (
            <li key={`f-${item.agent_id}-${item.name}`} className="outputs-row">
              {/* A confined download endpoint, not a route — a plain anchor is correct. */}
              <a
                className="outputs-open"
                href={`/api/outputs/file/${encodeURIComponent(item.agent_id)}/${encodeURIComponent(item.name ?? '')}`}
              >
                <span className="outputs-title">📎 {item.name}</span>
                <span className="muted"> — {t('outputs.fileExport')}</span>
              </a>
              <span className="outputs-meta">
                <span className="outputs-agent">{item.agent_id}</span>
                <span className="muted">{formatDateTime(item.ts) || item.ts}</span>
              </span>
            </li>
          ),
        )}
      </ul>
      {data?.truncated && <p className="muted">{t('outputs.truncated')}</p>}

      {openStep && (
        <div className="outputs-artifact">
          <button type="button" className="artifact-close" onClick={() => setOpenStep(null)}>
            ✕
          </button>
          <StepArtifactView
            step={{ taskId: openStep.task_id, seq: openStep.seq, title: openStep.step_title }}
          />
        </div>
      )}
    </section>
  )
}
