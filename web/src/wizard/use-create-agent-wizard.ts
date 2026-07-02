// Shared state machine for the create-agent wizard (CreateAgent.tsx). Plain useState —
// no new deps, matches the rest of the SPA's style. Steps are 1..5; state accumulates
// across steps and step 5 (Review) builds the POST body from it.
import { useMemo, useState } from 'react'
import type { CreateAgentBindings, CreateAgentSpec, Pack } from '../types'

export interface WizardState {
  step: number
  pack: Pack | null
  id: string
  name: string
  role: string
  goals: string
  persona: string
  personaEdited: boolean
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
  step: 1,
  pack: null,
  id: '',
  name: '',
  role: '',
  goals: '',
  persona: '',
  personaEdited: false,
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
    }
  }

  return {
    state,
    update,
    selectPack,
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
