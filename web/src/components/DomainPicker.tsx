// Step 1 of the create-agent wizard: loads GET /api/packs and renders a radio list of
// installed domain packs (name + the report kinds each pack serves). Selecting a pack is
// the input the rest of the wizard (reports/bindings) filters against.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useLanguage } from '../i18n/language-context'
import { KIND_LABEL, labelFor } from '../labels'
import type { Pack } from '../types'

export function DomainPicker({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (pack: Pack) => void
}) {
  const { t } = useLanguage()
  const [packs, setPacks] = useState<Pack[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getPacks()
      .then((res) => setPacks(res.packs))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('domainPicker.loadFailed')))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) return <p>{t('domainPicker.loading')}</p>
  if (error) return <p className="error">{t('domainPicker.errorPrefix', { message: error })}</p>
  if (packs.length === 0) return <p className="muted">{t('domainPicker.empty')}</p>

  return (
    <fieldset className="domain-picker">
      <legend>{t('domainPicker.legend')}</legend>
      {packs.map((p) => (
        <label key={p.id} className="domain-picker-option">
          <input
            type="radio"
            name="domain"
            value={p.id}
            checked={selected === p.id}
            onChange={() => onSelect(p)}
          />{' '}
          <strong>{p.name}</strong> <span className="muted">({p.id})</span>
          <div className="muted">
            {t('domainPicker.reportsLabel', {
              kinds: p.report_kinds.map((k) => labelFor(KIND_LABEL, k, t)).join(', ') || t('domainPicker.none'),
            })}
          </div>
        </label>
      ))}
    </fieldset>
  )
}
