// Wizard Step 4: binding fields per selected pack's servers. All optional except the
// client-side hint that stakeholder_channel should be included in external_channels
// (backend enforces this for real — see agent_create.py's stakeholder cross-check).
import type { WizardState } from './use-create-agent-wizard'

export function BindingsStep({
  state,
  update,
  stakeholderChannelMissing,
}: {
  state: WizardState
  update: <K extends keyof WizardState>(key: K, value: WizardState[K]) => void
  stakeholderChannelMissing: boolean
}) {
  const servers = new Set(state.pack?.servers ?? [])

  return (
    <section>
      <h3>Step 4: Bindings (optional)</h3>
      {servers.has('jira') && (
        <fieldset>
          <legend>Jira</legend>
          <label>
            Project key:{' '}
            <input value={state.jiraProjectKey} onChange={(e) => update('jiraProjectKey', e.target.value)} />
          </label>
        </fieldset>
      )}
      {servers.has('confluence') && (
        <fieldset>
          <legend>Confluence</legend>
          <label>
            Space key:{' '}
            <input
              value={state.confluenceSpaceKey}
              onChange={(e) => update('confluenceSpaceKey', e.target.value)}
            />
          </label>{' '}
          <label>
            Space id:{' '}
            <input
              value={state.confluenceSpaceId}
              onChange={(e) => update('confluenceSpaceId', e.target.value)}
            />
          </label>{' '}
          <label>
            OKR page id:{' '}
            <input
              value={state.confluenceOkrPageId}
              onChange={(e) => update('confluenceOkrPageId', e.target.value)}
            />
          </label>
        </fieldset>
      )}
      {servers.has('github') && (
        <fieldset>
          <legend>GitHub</legend>
          <label>
            Repo (owner/name):{' '}
            <input value={state.githubRepo} onChange={(e) => update('githubRepo', e.target.value)} />
          </label>
        </fieldset>
      )}
      {servers.has('slack') && (
        <fieldset>
          <legend>Slack</legend>
          <label>
            Report channel:{' '}
            <input
              value={state.slackReportChannel}
              onChange={(e) => update('slackReportChannel', e.target.value)}
            />
          </label>{' '}
          <label>
            Stakeholder channel:{' '}
            <input
              value={state.slackStakeholderChannel}
              onChange={(e) => update('slackStakeholderChannel', e.target.value)}
            />
          </label>{' '}
          <label>
            External channels (comma-list):{' '}
            <input
              value={state.slackExternalChannels}
              onChange={(e) => update('slackExternalChannels', e.target.value)}
              placeholder="C123,C456"
            />
          </label>
          {stakeholderChannelMissing && (
            <p className="muted">
              hint: stakeholder channel is usually also listed in external channels
            </p>
          )}
        </fieldset>
      )}
      {servers.size === 0 && <p className="muted">Selected pack declares no write servers.</p>}
    </section>
  )
}
