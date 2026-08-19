// Kỹ năng — which skill packs this agent may use, and which company-library docs get
// injected into its prompt. Both save the WHOLE selection (full replace, not a delta).
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../../../api/client'
import { Button } from '../../../components/ui/button'
import { useLanguage } from '../../../i18n/language-context'
import type { SkillsPayload } from '../../../types'

export function SkillsTab({ id }: { id: string }) {
  return (
    <div className="knowledge-tab">
      <SkillsPicker id={id} />
      <CompanyDocsPicker id={id} />
    </div>
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
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          {busy ? t('agentKnowledge.skillsSaving') : t('agentKnowledge.skillsSave')}
        </Button>
        {dirty && <span className="unsaved">{t('agentKnowledge.unsaved')}</span>}
        {saved && <span className="ok">{t('agentKnowledge.saved')}</span>}
      </div>
    </section>
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
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          {busy ? t('agentKnowledge.savingDocs') : t('agentKnowledge.saveDocs')}
        </Button>
        {dirty && <span className="unsaved">{t('agentKnowledge.unsaved')}</span>}
        {saved && <span className="ok">{t('agentKnowledge.saved')}</span>}
      </div>
    </section>
  )
}