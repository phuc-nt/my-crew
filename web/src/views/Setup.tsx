// First-run Setup Wizard (v7 M17): shown when the server has no auth configured yet. Walks
// the CEO through entering keys (per group, with a Test button), then sets a password and
// finishes — which writes .env, marks setup complete, and restarts the web service. After
// that the wizard is gone (410) and the app shows Login. No text editor, ever.
//
// One extra step (company name + coordinator) sits between the key groups and the
// password step, writing to `company.yaml` via POST /api/company — a plain config write,
// NOT gated by the setup wizard's localhost/lock guard (that guard protects .env/auth
// secrets; company identity has no secret in it). Auth is off until `finish`, so this call
// reaches the server the same way GET /api/agents already does pre-setup.
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import { Card } from '../components/ui/card'
import type { UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import type { AgentSummary } from '../types'
import { SetupCompanyStep } from './setup-company-step'

interface Field {
  key: string
  labelKey: UiKey
  type?: 'password' | 'text'
}

interface Group {
  id: string
  titleKey: UiKey
  fields: Field[]
  testable: boolean
  hintKey?: UiKey
}

// The steps. GitHub is auth'd via the `gh` CLI (no key field) — just a Test.
const GROUPS: Group[] = [
  {
    id: 'openrouter',
    titleKey: 'setup.group.openrouter.title',
    fields: [{ key: 'OPENROUTER_API_KEY', labelKey: 'setup.group.openrouter.apiKey', type: 'password' }],
    testable: true,
    hintKey: 'setup.group.openrouter.hint',
  },
  {
    id: 'atlassian',
    titleKey: 'setup.group.atlassian.title',
    fields: [
      { key: 'ATLASSIAN_SITE_NAME', labelKey: 'setup.group.atlassian.site' },
      { key: 'ATLASSIAN_USER_EMAIL', labelKey: 'setup.group.atlassian.email' },
      { key: 'ATLASSIAN_API_TOKEN', labelKey: 'setup.group.atlassian.apiToken', type: 'password' },
      { key: 'JIRA_PROJECT_KEY', labelKey: 'setup.group.atlassian.jiraProjectKey' },
    ],
    testable: true,
  },
  {
    id: 'slack',
    titleKey: 'setup.group.slack.title',
    fields: [
      { key: 'SLACK_XOXC_TOKEN', labelKey: 'setup.group.slack.xoxc', type: 'password' },
      { key: 'SLACK_XOXD_TOKEN', labelKey: 'setup.group.slack.xoxd', type: 'password' },
      { key: 'SLACK_TEAM_DOMAIN', labelKey: 'setup.group.slack.teamDomain' },
      { key: 'SLACK_REPORT_CHANNEL', labelKey: 'setup.group.slack.reportChannel' },
    ],
    testable: true,
  },
  {
    id: 'github',
    titleKey: 'setup.group.github.title',
    fields: [{ key: 'GITHUB_REPO', labelKey: 'setup.group.github.repo' }],
    testable: true,
    hintKey: 'setup.group.github.hint',
  },
  {
    id: 'websearch',
    titleKey: 'setup.group.websearch.title',
    fields: [
      { key: 'TAVILY_API_KEY', labelKey: 'setup.group.websearch.tavily', type: 'password' },
      { key: 'BRAVE_API_KEY', labelKey: 'setup.group.websearch.brave', type: 'password' },
    ],
    testable: false,
    hintKey: 'setup.group.websearch.hint',
  },
]

export function Setup({ onDone }: { onDone: () => void }) {
  const { t } = useLanguage()
  const [step, setStep] = useState(0) // 0..GROUPS.length-1 = key groups; then company; then password
  const [values, setValues] = useState<Record<string, string>>({})
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; detail: string }>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const companyStep = step === GROUPS.length
  const passwordStep = step === GROUPS.length + 1
  const [password, setPassword] = useState('')
  const [username, setUsername] = useState('admin')
  const [finished, setFinished] = useState(false)
  const [companyName, setCompanyName] = useState('')
  const [coordinatorId, setCoordinatorId] = useState('')
  const [agents, setAgents] = useState<AgentSummary[]>([])

  useEffect(() => {
    if (!companyStep) return
    api
      .getAgents()
      .then(setAgents)
      .catch(() => setAgents([])) // coordinator select is optional — a fetch failure must not block Setup
  }, [companyStep])

  const saveCompany = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      await api.saveCompany(companyName.trim(), coordinatorId || null)
      setStep((s) => s + 1)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('setup.saveCompanyFailed'))
    } finally {
      setBusy(false)
    }
  }, [companyName, coordinatorId, t])

  const setField = (key: string, v: string) => setValues((s) => ({ ...s, [key]: v }))

  const saveGroup = useCallback(
    async (g: Group) => {
      const toWrite: Record<string, string> = {}
      for (const f of g.fields) if (values[f.key]?.trim()) toWrite[f.key] = values[f.key]
      if (Object.keys(toWrite).length) await api.setupEnv(toWrite)
    },
    [values],
  )

  const test = useCallback(
    async (g: Group) => {
      setBusy(true)
      setError(null)
      try {
        await saveGroup(g) // persist before testing so the backend sees fresh values
        const r = await api.setupTest(g.id)
        setTestResult((s) => ({ ...s, [g.id]: { ok: r.ok, detail: r.detail } }))
      } catch (e: unknown) {
        setError(e instanceof ApiError ? e.message : t('setup.testFailed'))
      } finally {
        setBusy(false)
      }
    },
    [saveGroup, t],
  )

  const next = useCallback(
    async (g: Group) => {
      setBusy(true)
      setError(null)
      try {
        await saveGroup(g)
        setStep((s) => s + 1)
      } catch (e: unknown) {
        setError(e instanceof ApiError ? e.message : t('setup.saveFailed'))
      } finally {
        setBusy(false)
      }
    },
    [saveGroup, t],
  )

  const finish = useCallback(async () => {
    if (password.length < 6) {
      setError(t('setup.passwordTooShort'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.setupFinish(username, password)
      setFinished(true)
      // give launchd ~6s to restart, then re-check (App will show Login)
      setTimeout(onDone, 6000)
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : t('setup.finishFailed'))
      setBusy(false)
    }
  }, [password, username, onDone, t])

  if (finished) {
    return (
      <div className="setup-screen">
        <Card className="setup-box">
          <h1>{t('setup.restartingTitle')}</h1>
          <p>{t('setup.restartingBody')}</p>
        </Card>
      </div>
    )
  }

  return (
    <div className="setup-screen">
      <Card className="setup-box">
        <div className="setup-progress">
          {t('setup.progress', { step: step + 1, total: GROUPS.length + 2 })}
        </div>
        {companyStep ? (
          <SetupCompanyStep
            companyName={companyName}
            setCompanyName={setCompanyName}
            coordinatorId={coordinatorId}
            setCoordinatorId={setCoordinatorId}
            agents={agents}
            busy={busy}
            error={error}
            onBack={() => setStep((s) => s - 1)}
            onNext={() => void saveCompany()}
          />
        ) : !passwordStep ? (
          <>
            <h1>{t(GROUPS[step].titleKey)}</h1>
            {GROUPS[step].hintKey && <p className="setup-hint">{t(GROUPS[step].hintKey!)}</p>}
            {GROUPS[step].fields.map((f) => (
              <label key={f.key}>
                {t(f.labelKey)}
                <input
                  type={f.type ?? 'text'}
                  value={values[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              </label>
            ))}
            {testResult[GROUPS[step].id] && (
              <p className={testResult[GROUPS[step].id].ok ? 'setup-ok' : 'error'}>
                {testResult[GROUPS[step].id].ok ? t('setup.connectionOk') : '✗ '}
                {testResult[GROUPS[step].id].detail}
              </p>
            )}
            {error && <p className="error">{error}</p>}
            <div className="setup-actions">
              {/* v53: styled by container element selector (.setup-actions button) — unify in a later pass */}
              {GROUPS[step].testable && (
                <button type="button" disabled={busy} onClick={() => void test(GROUPS[step])}>
                  {t('setup.testConnection')}
                </button>
              )}
              {step > 0 && (
                <button type="button" disabled={busy} onClick={() => setStep((s) => s - 1)}>
                  {t('setup.back')}
                </button>
              )}
              <button
                type="button"
                className="setup-primary"
                disabled={busy}
                onClick={() => void next(GROUPS[step])}
              >
                {t('setup.continue')}
              </button>
            </div>
          </>
        ) : (
          <>
            <h1>{t('setup.passwordTitle')}</h1>
            <p className="setup-hint">{t('setup.passwordHint')}</p>
            <label>
              {t('setup.username')}
              <input value={username} onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label>
              {t('setup.passwordFieldLabel')}
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && <p className="error">{error}</p>}
            <div className="setup-actions">
              <button type="button" disabled={busy} onClick={() => setStep((s) => s - 1)}>
                {t('setup.back')}
              </button>
              <button
                type="button"
                className="setup-primary"
                disabled={busy || password.length < 6}
                onClick={() => void finish()}
              >
                {t('setup.finish')}
              </button>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
