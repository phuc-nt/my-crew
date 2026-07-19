// Wizard Step 5: JSON-ish summary of the spec that will be POSTed, a copy-to-clipboard
// .env template (NAMES only — secrets are never entered here, see env-template.ts), and
// the Create button. 400/409 surface the backend's exact `detail` string inline.
import { useState } from 'react'
import { Link } from 'react-router'
import { api, ApiError } from '../api/client'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { useLanguage } from '../i18n/language-context'
import type { CreateAgentResult, CreateAgentSpec } from '../types'
import { buildEnvTemplate } from './env-template'

export function ReviewStep({ spec, pack }: { spec: CreateAgentSpec; pack: { servers: string[] } | null }) {
  const { t } = useLanguage()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CreateAgentResult | null>(null)
  const [copied, setCopied] = useState(false)

  const envTemplate = buildEnvTemplate(pack?.servers ?? [])

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const res = await api.createAgent(spec)
      setResult(res)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : t('reviewStep.createFailed'))
    } finally {
      setBusy(false)
    }
  }

  async function copyEnv() {
    try {
      await navigator.clipboard.writeText(envTemplate)
      setCopied(true)
    } catch {
      /* clipboard unavailable — the text is still selectable below */
    }
  }

  return (
    <section>
      <h3>{t('reviewStep.title')}</h3>
      <pre className="review-spec">{JSON.stringify(spec, null, 2)}</pre>

      <Card className="token-setup-box">
        <h4>{t('reviewStep.tokenSetupTitle')}</h4>
        <p className="muted">{t('reviewStep.tokenSetupHint')}</p>
        <pre className="env-template">{envTemplate}</pre>
        <Button variant="ghost" onClick={copyEnv}>
          {copied ? t('reviewStep.envCopied') : t('reviewStep.envCopy')}
        </Button>
      </Card>

      {error && <p className="error">{t('reviewStep.errorPrefix', { message: error })}</p>}
      {!result && (
        <Button variant="ghost" disabled={busy} onClick={create}>
          {busy ? t('reviewStep.creating') : t('reviewStep.createAgent')}
        </Button>
      )}
      {result && (
        <p className="ok">
          {t('reviewStep.createdPrefix')}
          <strong>{result.created.id}</strong>
          {t('reviewStep.createdSuffix')}{' '}
          <Link to={`/agents/${result.created.id}`}>{t('reviewStep.openAgentPage')}</Link>
          {t('reviewStep.openAgentPageSuffix')}
        </p>
      )}
    </section>
  )
}
