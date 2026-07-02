// Wizard Step 5: JSON-ish summary of the spec that will be POSTed, a copy-to-clipboard
// .env template (NAMES only — secrets are never entered here, see env-template.ts), and
// the Create button. 400/409 surface the backend's exact `detail` string inline.
import { useState } from 'react'
import { Link } from 'react-router'
import { api, ApiError } from '../api/client'
import type { CreateAgentResult, CreateAgentSpec } from '../types'
import { buildEnvTemplate } from './env-template'

export function ReviewStep({ spec, pack }: { spec: CreateAgentSpec; pack: { servers: string[] } | null }) {
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
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'create failed')
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
      <h3>Step 5: Review + create</h3>
      <pre className="review-spec">{JSON.stringify(spec, null, 2)}</pre>

      <div className="token-setup-box">
        <h4>Token setup</h4>
        <p className="muted">
          These are environment variable NAMES only — never enter secret values here. A
          technical operator sets the actual values in the server's .env file.
        </p>
        <pre className="env-template">{envTemplate}</pre>
        <button type="button" onClick={copyEnv}>
          {copied ? 'Copied!' : 'Copy .env template'}
        </button>
      </div>

      {error && <p className="error">Error: {error}</p>}
      {!result && (
        <button type="button" disabled={busy} onClick={create}>
          {busy ? 'Creating…' : 'Create agent'}
        </button>
      )}
      {result && (
        <p className="ok">
          Created agent <strong>{result.created.id}</strong>. Go to{' '}
          <Link to="/team">Team</Link> to manage it.
        </p>
      )}
    </section>
  )
}
