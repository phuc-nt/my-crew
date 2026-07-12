// Shared state machine for the create-agent wizard (CreateAgent.tsx). Plain useState —
// no new deps, matches the rest of the SPA's style. Steps are 1..5; state accumulates
// across steps and step 5 (Review) builds the POST body from it.
import { useMemo, useState } from 'react'
import type { CreateAgentBindings, CreateAgentSpec, Pack, StaffTemplate } from '../types'

// Build the `agent_runtime` field of the create spec from the picked runtime. deep_agent needs a
// sandbox block (a bare 'deep_agent' string would be DOA — the backend fails closed with no
// sandbox), so it is emitted as a mapping with the self-hosted docker provider. create_agent is a
// bare string; native is omitted (the default).
function runtimeSpec(runtime: string): Pick<CreateAgentSpec, 'agent_runtime'> {
  if (runtime === 'deep_agent') {
    return { agent_runtime: { kind: 'deep_agent', sandbox: { provider: 'docker' } } }
  }
  if (runtime && runtime !== 'native') {
    return { agent_runtime: runtime }
  }
  return {}
}

export interface WizardState {
  step: number
  pack: Pack | null
  id: string
  name: string
  role: string
  goals: string
  persona: string
  personaEdited: boolean
  webSearch: boolean // opt-in profile flag; only meaningful for research-style roles
  agentRuntime: string // v20.5: 'native' | 'create_agent' | 'deep_agent'; prefilled from template
  // v30: '' = theo mặc định công ty (TRUST_MODE env); 'autonomous' | 'guarded' ghi tường minh
  // vào safety.trust_mode của profile.yaml.
  trustMode: '' | 'autonomous' | 'guarded'
  reports: string[]
  schedule: Record<string, string> // kind -> cron5 (only for scheduled kinds)
  jiraProjectKey: string
  confluenceSpaceKey: string
  confluenceSpaceId: string
  confluenceOkrPageId: string
  githubRepo: string
  slackReportChannel: string
  slackStakeholderChannel: string
  slackExternalChannels: string // comma-list, raw input
}

//: Fields that must reset when the selected pack changes — reports/schedule/bindings are
//: only valid for the pack that produced them (a report kind or server from the old pack
//: may not exist on the new one). id/name/persona are pack-independent and kept.
const PACK_SCOPED_RESET: Pick<
  WizardState,
  | 'reports'
  | 'schedule'
  | 'jiraProjectKey'
  | 'confluenceSpaceKey'
  | 'confluenceSpaceId'
  | 'confluenceOkrPageId'
  | 'githubRepo'
  | 'slackReportChannel'
  | 'slackStakeholderChannel'
  | 'slackExternalChannels'
> = {
  reports: [],
  schedule: {},
  jiraProjectKey: '',
  confluenceSpaceKey: '',
  confluenceSpaceId: '',
  confluenceOkrPageId: '',
  githubRepo: '',
  slackReportChannel: '',
  slackStakeholderChannel: '',
  slackExternalChannels: '',
}

const INITIAL: WizardState = {
  step: 0, // 0 = optional staff-template picker; 1 = domain picker
  pack: null,
  id: '',
  name: '',
  role: '',
  goals: '',
  persona: '',
  personaEdited: false,
  webSearch: false,
  agentRuntime: 'native', // safe default; template prefills a recommendation
  trustMode: '', // inherit the company-wide default unless the CEO picks explicitly
  ...PACK_SCOPED_RESET,
}

export function useCreateAgentWizard() {
  const [state, setState] = useState<WizardState>(INITIAL)

  function update<K extends keyof WizardState>(key: K, value: WizardState[K]) {
    setState((s) => ({ ...s, [key]: value }))
  }

  // Switching packs invalidates reports/schedule/bindings (M1 fix): a report kind or
  // server binding from the old pack may not exist on the new one, and silently keeping
  // it means Create fails with a 400 the operator has no obvious way to diagnose.
  function selectPack(pack: Pack) {
    setState((s) => ({ ...s, pack, ...PACK_SCOPED_RESET }))
  }

  function goTo(step: number) {
    setState((s) => ({ ...s, step }))
  }

  // Template prefill: templates are a PREFILL SOURCE ONLY — this sets the same
  // fields the operator could set by hand (pack, role, persona, reports), then the CEO
  // tunes/reviews before Create. `pack` is the resolved Pack for the template's domain
  // (the caller looks it up from GET /api/packs, matched by template.domain) so the
  // report-kind checkboxes and bindings step render correctly. Report kinds not actually
  // served by the resolved pack are dropped (defends against a stale/hand-edited
  // template.yaml naming a kind the installed pack no longer serves).
  function applyTemplate(template: StaffTemplate, pack: Pack) {
    const validReports = template.reports.filter((k) => pack.report_kinds.includes(k))
    setState((s) => ({
      ...s,
      pack,
      ...PACK_SCOPED_RESET,
      reports: validReports,
      role: template.role,
      persona: template.persona,
      personaEdited: template.persona.trim() !== '', // stop IdentityStep auto-regenerating over it
      webSearch: template.web_search,
      agentRuntime: template.recommended_runtime || 'native', // v20.5 prefill; user can override
    }))
  }

  function toggleReport(kind: string) {
    setState((s) => {
      const has = s.reports.includes(kind)
      const reports = has ? s.reports.filter((k) => k !== kind) : [...s.reports, kind]
      const schedule = { ...s.schedule }
      if (has) delete schedule[kind]
      return { ...s, reports, schedule }
    })
  }

  function setCronFor(kind: string, cron: string | null) {
    setState((s) => {
      const schedule = { ...s.schedule }
      if (cron) schedule[kind] = cron
      else delete schedule[kind]
      return { ...s, schedule }
    })
  }

  const externalChannelsList = useMemo(
    () =>
      state.slackExternalChannels
        .split(',')
        .map((c) => c.trim())
        .filter(Boolean),
    [state.slackExternalChannels],
  )

  // client-side hint (S9 spec): stakeholder_channel must be included in external_channels
  // if set. Backend re-validates — this is only a UX nudge.
  const stakeholderChannelMissing =
    state.slackStakeholderChannel.trim() !== '' &&
    !externalChannelsList.includes(state.slackStakeholderChannel.trim())

  function buildSpec(): CreateAgentSpec {
    const bindings: CreateAgentBindings = {}
    if (state.jiraProjectKey.trim()) bindings.jira = { project_key: state.jiraProjectKey.trim() }
    if (state.confluenceSpaceKey.trim() || state.confluenceSpaceId.trim() || state.confluenceOkrPageId.trim()) {
      bindings.confluence = {
        ...(state.confluenceSpaceKey.trim() ? { space_key: state.confluenceSpaceKey.trim() } : {}),
        ...(state.confluenceSpaceId.trim() ? { space_id: state.confluenceSpaceId.trim() } : {}),
        ...(state.confluenceOkrPageId.trim() ? { okr_page_id: state.confluenceOkrPageId.trim() } : {}),
      }
    }
    if (state.githubRepo.trim()) bindings.github = { repo: state.githubRepo.trim() }
    if (
      state.slackReportChannel.trim() ||
      state.slackStakeholderChannel.trim() ||
      externalChannelsList.length > 0
    ) {
      bindings.slack = {
        ...(state.slackReportChannel.trim() ? { report_channel: state.slackReportChannel.trim() } : {}),
        ...(state.slackStakeholderChannel.trim()
          ? { stakeholder_channel: state.slackStakeholderChannel.trim() }
          : {}),
        ...(externalChannelsList.length > 0 ? { external_channels: externalChannelsList } : {}),
      }
    }

    return {
      id: state.id.trim().toLowerCase(),
      name: state.name.trim() || state.id.trim(),
      domain: state.pack?.id ?? '',
      reports: state.reports,
      schedule: state.schedule,
      bindings,
      ...(state.persona.trim() ? { persona: state.persona.trim() } : {}),
      ...(state.webSearch ? { web_search: true } : {}),
      ...(state.trustMode ? { trust_mode: state.trustMode } : {}),
      ...runtimeSpec(state.agentRuntime),
    }
  }

  return {
    state,
    update,
    selectPack,
    applyTemplate,
    goTo,
    toggleReport,
    setCronFor,
    externalChannelsList,
    stakeholderChannelMissing,
    buildSpec,
  }
}

// Mirrors the backend's agent id rule exactly (src/runtime/agent_paths.py:_AGENT_ID_RE):
// lowercase alnum start, then alnum/'-'/'_' — no leading '-', underscore allowed.
export const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/
