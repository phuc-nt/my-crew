// Maps a pack's `servers` list to the .env variable NAMES the technical operator must
// set on the server — mirrors src/server/integration_health.py's checks exactly (kept in
// sync by hand). NEVER include a secret VALUE here, only names + a placeholder.

const SERVER_ENV_VARS: Record<string, { names: string[]; note: string }> = {
  jira: {
    names: ['ATLASSIAN_SITE_NAME', 'ATLASSIAN_USER_EMAIL', 'ATLASSIAN_API_TOKEN'],
    note: 'Shared Atlassian API token (also covers Confluence).',
  },
  confluence: {
    names: ['ATLASSIAN_SITE_NAME', 'ATLASSIAN_USER_EMAIL', 'ATLASSIAN_API_TOKEN'],
    note: 'Shared Atlassian API token (also covers Jira).',
  },
  slack: {
    names: ['SLACK_XOXC_TOKEN', 'SLACK_XOXD_TOKEN', 'SLACK_TEAM_DOMAIN'],
    note: 'Slack browser-session tokens.',
  },
  github: {
    names: [],
    note: 'No .env token — run `gh auth login` on the server instead.',
  },
  linear: {
    names: ['LINEAR_API_KEY'],
    note: 'Linear personal API key.',
  },
}

/** Deterministic .env template text (NAMES only, no values) for the given pack servers. */
export function buildEnvTemplate(servers: string[]): string {
  const lines: string[] = ['# .env additions for this agent — set VALUES on the server only.']
  const seen = new Set<string>()
  for (const server of servers) {
    const entry = SERVER_ENV_VARS[server]
    if (!entry) continue
    lines.push(`# ${server}: ${entry.note}`)
    for (const name of entry.names) {
      if (seen.has(name)) continue
      seen.add(name)
      lines.push(`${name}=`)
    }
  }
  if (lines.length === 1) lines.push('# (no extra tokens needed for this pack)')
  return lines.join('\n')
}
