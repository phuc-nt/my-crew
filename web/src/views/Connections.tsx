// v33 P1: "Kết nối" — the UI version of .env, fixed catalog. One card per known
// integration: live status dot + which keys are set (presence only — a value is never
// shown back) + a small form to enter/replace values. Writes go to the server's
// whitelisted merge path; the running process only sees new values after a restart,
// so a successful save shows the restart banner instead of pretending it's live.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import type { ConnectionCard } from '../types'

function CardForm({ card, onSaved }: { card: ConnectionCard; onSaved: () => void }) {
  const { t } = useLanguage()
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState(0)

  const dirty = Object.values(values).some((v) => v.trim() !== '')

  const save = () => {
    const updates = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim() !== ''),
    )
    setBusy(true)
    setError(null)
    api
      .putConnectionKeys(updates)
      .then(() => {
        setValues({})
        setSavedAt(Date.now())
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
        {savedAt > 0 && !dirty && <span className="muted">{t('connections.saved')}</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  )
}

export function Connections() {
  const { t } = useLanguage()
  const [cards, setCards] = useState<ConnectionCard[]>([])
  const [needsRestart, setNeedsRestart] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [restartMsg, setRestartMsg] = useState<string | null>(null)
  const [restarting, setRestarting] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getConnections()
      .then((res) => {
        setCards(res.cards)
        setNeedsRestart(res.needs_restart)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('connections.loadFailed')))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const restart = () => {
    if (!window.confirm(t('connections.restartConfirm'))) return
    setRestarting(true)
    setRestartMsg(null)
    api
      .restartService()
      .then((res) => setRestartMsg(res.message))
      .catch((e: unknown) => setRestartMsg(e instanceof Error ? e.message : t('connections.restartCallFailed')))
      .finally(() => setRestarting(false))
  }

  return (
    <section className="connections-page">
      <PageHeader title={t('connections.title')} />
      <p className="muted">{t('connections.intro')}</p>

      {needsRestart && (
        <div className="connection-restart-banner" role="status">
          <span>{t('connections.restartBannerText')}</span>
          <Button variant="ghost" disabled={restarting} onClick={restart}>
            {restarting ? t('connections.restarting') : t('connections.restart')}
          </Button>
        </div>
      )}
      {restartMsg && <p className="muted">{restartMsg}</p>}

      {loading && <p className="muted">{t('connections.checking')}</p>}
      {error && <p className="error">{error}</p>}

      <div className="connection-grid">
        {cards.map((card) => (
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
            <CardForm card={card} onSaved={load} />
          </Card>
        ))}
      </div>
    </section>
  )
}
