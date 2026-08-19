// Kết nối — the UI version of .env, ported from the standalone Connections view.
//
// Values are write-only by design: the card says whether a key IS set, never what it is.
// A save only lands in the file, so a successful write shows the restart banner rather
// than pretending the running process already picked it up.
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useConnections } from '../../api/queries/use-system-queries'
import { queryKeys } from '../../api/queries/query-keys'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { useLanguage } from '../../i18n/language-context'
import type { ConnectionCard } from '../../types'

function CardForm({ card, onSaved }: { card: ConnectionCard; onSaved: () => void }) {
  const { t } = useLanguage()
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const dirty = Object.values(values).some((v) => v.trim() !== '')

  const save = () => {
    const updates = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== ''))
    setBusy(true)
    setError(null)
    api
      .putConnectionKeys(updates)
      .then(() => {
        setValues({})
        setSaved(true)
        onSaved()
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('connections.saveFailed')))
      .finally(() => setBusy(false))
  }

  if (card.keys.length === 0) return null
  return (
    <div className="connection-form">
      {card.keys.map((k) => (
        <label key={k.name} className="connection-key-row">
          <span className="connection-key-name">
            {k.name}
            <span className={k.set ? 'key-set' : 'key-unset'}>
              {k.set ? t('connections.set') : t('connections.unset')}
            </span>
          </span>
          <input
            type="password"
            autoComplete="off"
            placeholder={k.set ? t('connections.placeholderSet') : t('connections.placeholderUnset')}
            value={values[k.name] ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, [k.name]: e.target.value }))}
          />
        </label>
      ))}
      <div className="connection-form-actions">
        <Button variant="ghost" disabled={!dirty || busy} onClick={save}>
          {busy ? t('connections.saving') : t('connections.save')}
        </Button>
        {saved && !dirty && <span className="muted">{t('connections.saved')}</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  )
}

export function ConnectionsTab() {
  const { t } = useLanguage()
  const qc = useQueryClient()
  const { data, isLoading, isError } = useConnections()
  const [restartMsg, setRestartMsg] = useState<string | null>(null)
  const [restarting, setRestarting] = useState(false)

  const reload = () => void qc.invalidateQueries({ queryKey: queryKeys.system.connections() })

  const restart = () => {
    if (!window.confirm(t('connections.restartConfirm'))) return
    setRestarting(true)
    setRestartMsg(null)
    api
      .restartService()
      .then((res) => setRestartMsg(res.message))
      .catch((e: unknown) =>
        setRestartMsg(e instanceof Error ? e.message : t('connections.restartCallFailed')),
      )
      .finally(() => setRestarting(false))
  }

  return (
    <div className="connections-page">
      <p className="muted">{t('connections.intro')}</p>

      {data?.needs_restart && (
        <div className="connection-restart-banner" role="status">
          <span>{t('connections.restartBannerText')}</span>
          <Button variant="ghost" disabled={restarting} onClick={restart}>
            {restarting ? t('connections.restarting') : t('connections.restart')}
          </Button>
        </div>
      )}
      {restartMsg && <p className="muted">{restartMsg}</p>}

      {isLoading && <p className="muted">{t('connections.checking')}</p>}
      {isError && <p className="error">{t('connections.loadFailed')}</p>}

      <div className="connection-grid">
        {(data?.cards ?? []).map((card) => (
          <Card key={card.id} className="connection-card">
            <header className="connection-card-header">
              <span
                className={card.ok ? 'health-dot health-dot-ok' : 'health-dot health-dot-fail'}
                aria-hidden
              />
              <h3>{card.label}</h3>
            </header>
            {card.detail && <p className="muted connection-detail">{card.detail}</p>}
            {!card.ok && card.hint && <p className="connection-hint">{card.hint}</p>}
            {card.note && <p className="muted connection-note">{card.note}</p>}
            <CardForm card={card} onSaved={reload} />
          </Card>
        ))}
      </div>
    </div>
  )
}
