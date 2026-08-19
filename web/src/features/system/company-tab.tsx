// Công ty — who the company is (identity) and what every agent reads (shared docs).
//
// The per-agent config files are NOT here: they belong to one agent, so they stay on that
// agent's 🔬 Advanced tab. This tab holds only what is company-wide.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, api } from '../../api/client'
import { useCompany, useCompanyDocs } from '../../api/queries/use-system-queries'
import { queryKeys } from '../../api/queries/query-keys'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import type { CompanyDoc } from '../../types'

function CompanyIdentity() {
  const { t } = useLanguage()
  const qc = useQueryClient()
  const { data: company } = useCompany()
  const [name, setName] = useState('')
  const [coordinator, setCoordinator] = useState('')
  const [cap, setCap] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Seed the form once the payload lands; the fields stay user-owned after that.
  useEffect(() => {
    if (!company) return
    setName(company.name)
    setCoordinator(company.coordinator_id ?? '')
    setCap(String(company.team_task_cap_usd))
  }, [company])

  const save = () => {
    if (!company) return
    setBusy(true)
    setSaved(false)
    setError(null)
    // auto-confirm is owned by the settings tab — re-send it unchanged so saving identity
    // here can never silently flip how work gets confirmed.
    api
      .saveCompany(name, coordinator, Number(cap), company.team_task_auto_confirm)
      .then(() => {
        setSaved(true)
        return qc.invalidateQueries({ queryKey: queryKeys.team.company() })
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('settings.saveFailed')))
      .finally(() => setBusy(false))
  }

  if (!company) return <p>{t('companyDocs.loading')}</p>
  return (
    <section className="company-identity">
      <h3>{t('systemCompany.identityTitle')}</h3>
      <label>
        {t('systemCompany.nameLabel')}
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t('systemCompany.coordinatorLabel')}
        <input value={coordinator} onChange={(e) => setCoordinator(e.target.value)} />
      </label>
      <label>
        {t('systemCompany.capLabel')}
        <input
          type="number"
          step="0.01"
          value={cap}
          onChange={(e) => setCap(e.target.value)}
        />
      </label>
      <div className="agent-actions">
        <Button variant="primary" disabled={busy || !name.trim()} onClick={save}>
          {busy ? t('systemCompany.saving') : t('systemCompany.save')}
        </Button>
        {saved && <span className="muted">{t('systemCompany.saved')}</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </section>
  )
}

function DocEditor({
  doc,
  onDone,
  onCancel,
}: {
  doc: CompanyDoc | null
  onDone: () => void
  onCancel: () => void
}) {
  const { t } = useLanguage()
  const [title, setTitle] = useState(doc?.title ?? '')
  const [body, setBody] = useState(doc?.body ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    const today = new Date().toISOString().slice(0, 10)
    try {
      if (doc) await api.updateCompanyDoc(doc.slug, title, body, today)
      else await api.createCompanyDoc(title, body, today)
      onDone()
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('companyDocs.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!doc) return
    if (!window.confirm(t('companyDocs.deleteConfirm', { title: doc.title }))) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteCompanyDoc(doc.slug)
      onDone()
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('companyDocs.deleteFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="company-doc-editor">
      <label>
        {t('companyDocs.titleLabel')}
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('companyDocs.titlePlaceholder')}
        />
      </label>
      <label>
        {t('companyDocs.bodyLabel')}
        <textarea rows={16} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="agent-actions">
        <Button variant="primary" disabled={busy || !title.trim()} onClick={() => void save()}>
          {busy ? t('companyDocs.saving') : t('companyDocs.save')}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t('companyDocs.cancel')}
        </Button>
        {doc && (
          <Button variant="danger" disabled={busy} onClick={() => void remove()}>
            {t('companyDocs.delete')}
          </Button>
        )}
      </div>
    </div>
  )
}

function CompanyDocsSection() {
  const { t } = useLanguage()
  const qc = useQueryClient()
  const { data, isLoading, isError } = useCompanyDocs()
  const [selected, setSelected] = useState<CompanyDoc | 'new' | null>(null)

  const close = () => {
    setSelected(null)
    void qc.invalidateQueries({ queryKey: queryKeys.system.companyDocs() })
  }

  if (isLoading) return <p>{t('companyDocs.loading')}</p>
  if (isError) return <p className="error">{t('companyDocs.loadError')}</p>
  const docs = data?.docs ?? []

  return (
    <section className="company-docs">
      <h3>{t('systemCompany.docsTitle')}</h3>
      <p className="muted">{t('companyDocs.intro')}</p>
      <Button variant="ghost" onClick={() => setSelected('new')}>
        {t('companyDocs.new')}
      </Button>
      <div className="company-docs-body">
        <ul className="company-docs-list">
          {docs.length === 0 && <li className="muted">{t('companyDocs.empty')}</li>}
          {docs.map((d) => (
            <li key={d.slug}>
              <button
                type="button"
                className={selected !== 'new' && selected?.slug === d.slug ? 'active' : undefined}
                onClick={() => setSelected(d)}
              >
                <strong>{d.title}</strong>
                {d.updated && <span className="muted"> · {d.updated}</span>}
              </button>
            </li>
          ))}
        </ul>
        {selected && (
          <DocEditor
            // Remount on a different doc so the editor re-seeds from the new body.
            key={selected === 'new' ? 'new' : selected.slug}
            doc={selected === 'new' ? null : selected}
            onDone={close}
            onCancel={() => setSelected(null)}
          />
        )}
      </div>
    </section>
  )
}

export function CompanyTab() {
  const { t } = useLanguage()
  return (
    <div className="system-company">
      <CompanyIdentity />
      <CompanyDocsSection />
      <p className="muted">{t('systemCompany.configHint')}</p>
    </div>
  )
}
