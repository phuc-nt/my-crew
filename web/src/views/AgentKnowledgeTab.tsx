// v7 M18b: the Knowledge tab of the agent page — SOUL/PROJECT edited as a form (↔ markdown,
// with a raw fallback when the file was hand-edited) + a skills picker. Split out of
// AgentPage.tsx to keep that view focused; the tab is self-contained (own state + api calls).
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import type { KnowledgePayload, SkillsPayload } from '../types'

// Form field labels MIRROR src/agent/knowledge_template.py — same keys, same order. The
// backend owns the markdown shape; the UI only collects the values keyed by these names.
const KNOWLEDGE_FIELDS: Record<'soul' | 'project', { key: string; labelKey: UiKey; big: boolean }[]> = {
  soul: [
    { key: 'role', labelKey: 'agentKnowledge.soulRole', big: false },
    { key: 'tone', labelKey: 'agentKnowledge.soulTone', big: false },
    { key: 'rules', labelKey: 'agentKnowledge.soulRules', big: true },
  ],
  project: [
    { key: 'team', labelKey: 'agentKnowledge.projectTeam', big: true },
    { key: 'conventions', labelKey: 'agentKnowledge.projectConventions', big: true },
    { key: 'notes', labelKey: 'agentKnowledge.projectNotes', big: true },
  ],
}

export function KnowledgeTab({ id }: { id: string }) {
  const { t } = useLanguage()
  return (
    <div className="knowledge-tab">
      <KnowledgeDoc id={id} doc="soul" title={t('agentKnowledge.soulTitle')} />
      <KnowledgeDoc id={id} doc="project" title={t('agentKnowledge.projectTitle')} />
      <SkillsPicker id={id} />
      <CompanyDocsPicker id={id} />
    </div>
  )
}

// v7 M19: tick which company-library docs THIS agent reads. Writes the profile's
// `company_docs:` list; the ticked docs inject into the agent's internal prompt.
function CompanyDocsPicker({ id }: { id: string }) {
  const { t } = useLanguage()
  const [docs, setDocs] = useState<{ slug: string; title: string; selected: boolean }[] | null>(
    null,
  )
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    api
      .getAgentCompanyDocs(id)
      .then((d) => {
        setDocs(d.docs)
        setChosen(new Set(d.docs.filter((x) => x.selected).map((x) => x.slug)))
        setDirty(false)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('agentKnowledge.docLoadFailed')))
  }, [id, t])

  const toggle = (slug: string) => {
    setDirty(true)
    setSaved(false)
    setChosen((p) => {
      const next = new Set(p)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  const save = useCallback(async () => {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await api.putAgentCompanyDocs(id, [...chosen])
      setSaved(true)
      setDirty(false)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('agentKnowledge.saveDocsFailed'))
    } finally {
      setBusy(false)
    }
  }, [id, chosen, t])

  if (error) return <p className="error">{t('agentKnowledge.docErrorPrefix', { message: error })}</p>
  if (!docs) return <p>{t('agentKnowledge.docLoading', { title: t('agentKnowledge.companyDocsTitle') })}</p>

  return (
    <section className="company-docs-picker">
      <h3>{t('agentKnowledge.companyDocsTitle')}</h3>
      {docs.length === 0 ? (
        <p className="muted">{t('agentKnowledge.companyDocsEmpty')}</p>
      ) : (
        <ul className="skills-list">
          {docs.map((d) => (
            <li key={d.slug}>
              <label>
                <input
                  type="checkbox"
                  checked={chosen.has(d.slug)}
                  onChange={() => toggle(d.slug)}
                />
                <strong>{d.title}</strong>
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="agent-actions">
        {/* v53: styled by container element selector (.agent-actions button) — unify in a later pass */}
        <button type="button" disabled={busy} onClick={() => void save()}>
          {busy ? t('agentKnowledge.savingDocs') : t('agentKnowledge.saveDocs')}
        </button>
        {dirty && <span className="unsaved">{t('agentKnowledge.unsaved')}</span>}
        {saved && <span className="ok">{t('agentKnowledge.saved')}</span>}
      </div>
    </section>
  )
}

// One SOUL/PROJECT document edited as a FORM. When the file was hand-edited past the markers
// the backend returns raw_mode — we then show the raw markdown textarea instead of guessing a
// form (matches the backend contract; the form must never clobber prose it can't represent).
function KnowledgeDoc({ id, doc, title }: { id: string; doc: 'soul' | 'project'; title: string }) {
  const { t } = useLanguage()
  const [data, setData] = useState<KnowledgePayload | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [rawText, setRawText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [dirty, setDirty] = useState(false)

  const load = useCallback(() => {
    api
      .getKnowledge(id, doc)
      .then((d) => {
        setData(d)
        setFields(d.fields)
        setRawText(d.raw)
        setDirty(false)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('agentKnowledge.docLoadFailed')))
  }, [id, doc, t])
  useEffect(load, [load])

  const edit = () => {
    setDirty(true)
    setSaved(false)
  }

  const save = useCallback(async () => {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      if (data?.raw_mode) await api.putKnowledgeRaw(id, doc, rawText)
      else await api.putKnowledgeForm(id, doc, fields)
      setSaved(true)
      setDirty(false)
      load() // re-read so raw_mode flips correctly if the edit changed the markers
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('agentKnowledge.docSaveFailed'))
    } finally {
      setBusy(false)
    }
  }, [id, doc, data, fields, rawText, load, t])

  if (error) return <p className="error">{t('agentKnowledge.docErrorPrefix', { message: error })}</p>
  if (!data) return <p>{t('agentKnowledge.docLoading', { title })}</p>

  return (
    <section className="knowledge-doc">
      <h3>{title}</h3>
      {data.raw_mode ? (
        <>
          <p className="muted">{t('agentKnowledge.rawModeHint')}</p>
          <textarea
            rows={8}
            value={rawText}
            onChange={(e) => {
              edit()
              setRawText(e.target.value)
            }}
          />
        </>
      ) : (
        KNOWLEDGE_FIELDS[doc].map((f) => (
          <label key={f.key}>
            {t(f.labelKey)}
            {f.big ? (
              <textarea
                rows={4}
                value={fields[f.key] ?? ''}
                onChange={(e) => {
                  edit()
                  setFields((p) => ({ ...p, [f.key]: e.target.value }))
                }}
              />
            ) : (
              <input
                value={fields[f.key] ?? ''}
                onChange={(e) => {
                  edit()
                  setFields((p) => ({ ...p, [f.key]: e.target.value }))
                }}
              />
            )}
          </label>
        ))
      )}
      <div className="agent-actions">
        <button type="button" disabled={busy} onClick={() => void save()}>
          {busy ? t('agentKnowledge.saving') : t('agentKnowledge.save')}
        </button>
        {dirty && <span className="unsaved">{t('agentKnowledge.unsaved')}</span>}
        {saved && <span className="ok">{t('agentKnowledge.saved')}</span>}
      </div>
    </section>
  )
}

function SkillsPicker({ id }: { id: string }) {
  const { t } = useLanguage()
  const [data, setData] = useState<SkillsPayload | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    api
      .getSkills(id)
      .then((d) => {
        setData(d)
        setChosen(new Set(d.skills.filter((s) => s.selected).map((s) => s.name)))
        setDirty(false)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('agentKnowledge.skillsLoadFailed')))
  }, [id, t])

  const toggle = (name: string) => {
    setDirty(true)
    setSaved(false)
    setChosen((p) => {
      const next = new Set(p)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const save = useCallback(async () => {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await api.putSkills(id, [...chosen])
      setSaved(true)
      setDirty(false)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('agentKnowledge.skillsSaveFailed'))
    } finally {
      setBusy(false)
    }
  }, [id, chosen, t])

  if (error) return <p className="error">{t('agentKnowledge.skillsErrorPrefix', { message: error })}</p>
  if (!data) return <p>{t('agentKnowledge.skillsLoading')}</p>

  return (
    <section className="skills-picker">
      <h3>{t('agentKnowledge.skillsTitle')}</h3>
      {data.skills.length === 0 ? (
        <p className="muted">{t('agentKnowledge.skillsEmpty')}</p>
      ) : (
        <ul className="skills-list">
          {data.skills.map((s) => (
            <li key={s.name}>
              <label>
                <input
                  type="checkbox"
                  checked={chosen.has(s.name)}
                  onChange={() => toggle(s.name)}
                />
                <strong>{s.name}</strong> — <span className="muted">{s.description}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="agent-actions">
        <button type="button" disabled={busy} onClick={() => void save()}>
          {busy ? t('agentKnowledge.skillsSaving') : t('agentKnowledge.skillsSave')}
        </button>
        {dirty && <span className="unsaved">{t('agentKnowledge.unsaved')}</span>}
        {saved && <span className="ok">{t('agentKnowledge.saved')}</span>}
      </div>
    </section>
  )
}
