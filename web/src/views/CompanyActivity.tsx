// "Hoạt động" (route /company-activity, v31 P1): the fleet-wide post-hoc audit surface of
// autonomy-first — every agent's gateway decisions, runs, and team-step attempts in one
// newest-first table. CEO-primary nav (NOT gated behind high ui-mode: reviewing what the
// autonomous fleet did is the core low-tech workflow). Read-only; consumes
// /api/company/activity which projects to a server-side allowlist.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { DICT, type UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import type { CompanyActivityItem, CompanyActivityPayload } from '../types'

const PAGE = 50

const SOURCE_LABEL_KEY: Record<CompanyActivityItem['source'], UiKey> = {
  audit: 'companyActivity.sourceAudit',
  run: 'companyActivity.sourceRun',
  capture: 'companyActivity.sourceCapture',
}

const DAY_CHOICE_KEYS: { days: number; labelKey: UiKey }[] = [
  { days: 1, labelKey: 'companyActivity.dayToday' },
  { days: 7, labelKey: 'companyActivity.day7' },
  { days: 31, labelKey: 'companyActivity.day31' },
]

function sinceIso(days: number): string {
  return new Date(Date.now() - days * 24 * 3600 * 1000).toISOString()
}

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

// One human line per item, per source — mirrors the ops-chat summarizer's projection.
// Optional `t`: this is only ever called from within CompanyActivity() (which has the
// translator in scope), but keeping the fallback matches the pattern used elsewhere for
// module-level pure functions that render FE-static copy.
function describe(it: CompanyActivityItem, t: Translate = (key) => DICT.vi[key]): string {
  if (it.source === 'audit') {
    const head = [it.action_type, it.tool].filter(Boolean).join(':')
    // v46: show the actor when it differs from the log owner (agent_id) — e.g. a coordinated
    // or deep_team action performed by another agent under this agent's context.
    const who = it.actor && it.actor !== it.agent_id ? t('companyActivity.byActor', { actor: it.actor }) : ''
    return (it.reason ? `${head} — ${it.reason}` : head) + who
  }
  if (it.source === 'run') {
    const head = t('companyActivity.runLine', { kind: it.kind ?? '?', audience: it.audience ?? '?' })
    return it.delivered ? `${head}${t('companyActivity.delivered')}` : head
  }
  return t('companyActivity.captureLine', {
    stepType: it.step_type ?? '?',
    engine: it.engine ?? '?',
    taskId: it.task_id ?? '?',
  })
}

function statusOf(it: CompanyActivityItem): string {
  // Backend-origin data (verdict/status enum) — left untranslated by design.
  return (it.source === 'audit' ? it.verdict : it.status) ?? ''
}

export function CompanyActivity() {
  const { t } = useLanguage()
  const [data, setData] = useState<CompanyActivityPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [agent, setAgent] = useState('')
  const [verdict, setVerdict] = useState('')
  const [days, setDays] = useState(7)
  const [limit, setLimit] = useState(PAGE)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getCompanyActivity({
        limit,
        since: sinceIso(days),
        agent: agent || undefined,
        verdict: verdict || undefined,
      })
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [agent, verdict, days, limit])

  useEffect(() => {
    load()
  }, [load])

  const items = data?.items ?? []
  const sourceLabel = useMemo(
    () => (source: CompanyActivityItem['source']) => t(SOURCE_LABEL_KEY[source] ?? source),
    [t],
  )
  return (
    <section>
      <PageHeader title={t('companyActivity.title')} />
      <p>{t('companyActivity.intro')}</p>
      <div className="filter-row">
        <label>
          {t('companyActivity.filterAgent')}{' '}
          <select value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">{t('companyActivity.filterAll')}</option>
            {(data?.agents ?? []).map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>{' '}
        <label>
          {t('companyActivity.filterVerdict')}{' '}
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="">{t('companyActivity.filterAll')}</option>
            <option value="allow">{t('companyActivity.verdictAllow')}</option>
            <option value="deny">{t('companyActivity.verdictDeny')}</option>
            <option value="dry_run">{t('companyActivity.verdictDryRun')}</option>
          </select>
        </label>{' '}
        <label>
          {t('companyActivity.filterTime')}{' '}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAY_CHOICE_KEYS.map((c) => (
              <option key={c.days} value={c.days}>
                {t(c.labelKey)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {verdict && (
        <p className="muted">
          {t('companyActivity.verdictFilterHint')}
        </p>
      )}
      {loading && <p>{t('companyActivity.loading')}</p>}
      {error && <p className="error">{t('team.errorPrefix', { message: error })}</p>}
      {!loading && !error && items.length === 0 && (
        <EmptyState>{t('companyActivity.empty')}</EmptyState>
      )}
      {(data?.skipped.length ?? 0) > 0 && (
        <p className="error">{t('companyActivity.skippedNotice', { ids: data?.skipped.join(', ') ?? '' })}</p>
      )}
      {items.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('companyActivity.colTime')}</th>
              <th>{t('companyActivity.colAgent')}</th>
              <th>{t('companyActivity.colKind')}</th>
              <th>{t('companyActivity.colAction')}</th>
              <th>{t('companyActivity.colResult')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={`${it.ts}-${it.agent_id}-${i}`}>
                <td>{(it.ts ?? '').slice(0, 19).replace('T', ' ')}</td>
                <td>{it.agent_id}</td>
                <td>{sourceLabel(it.source)}</td>
                <td>{describe(it, t)}</td>
                <td>{statusOf(it)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {items.length >= limit && (
        <Button variant="ghost" onClick={() => setLimit((n) => n + PAGE)}>
          {t('companyActivity.loadMore')}
        </Button>
      )}
    </section>
  )
}
