// Kiến thức — SOUL and PROJECT edited as a form (↔ markdown, with a raw fallback when the
// file was hand-edited past its markers). Ported from the old agent page's knowledge tab;
// the skills and company-docs pickers moved to their own tab.
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../../../api/client'
import { Button } from '../../../components/ui/button'
import type { UiKey } from '../../../i18n/dictionary'
import { useLanguage } from '../../../i18n/language-context'
import type { KnowledgePayload } from '../../../types'

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
    </div>
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
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          {busy ? t('agentKnowledge.saving') : t('agentKnowledge.save')}
        </Button>
        {dirty && <span className="unsaved">{t('agentKnowledge.unsaved')}</span>}
        {saved && <span className="ok">{t('agentKnowledge.saved')}</span>}
      </div>
    </section>
  )
}