// v9 P1 — human-readable summary of a Lớp B action for the approve dialog.
//
// THE TRUST SURFACE: the CEO approves this to let the agent act for real. The summary MUST
// read the ACTUAL field-shape (never guess), and must NOT hide the sensitive dimension
// (where a message/email goes). The raw JSON stays available in <details> as the source of
// truth — the summary is a convenience, not a replacement. An action-type we don't recognise
// falls back to a readable one-liner (not blank), never a silent gap.
//
// Field-shape (verified against backend action builders):
// - mcp_tool: fields nested in `action.args` with camelCase keys (projectKey, summary, channel,
//   text, title, issueKey). NOT top-level.
// - email_send: `to` / `subject` at TOP-LEVEL (not in args).
// - gh_cli: only `argv: string[]` (no server/tool/args).
//
// v53 i18n: this is a plain function (called from ConfirmDialog.tsx, which has language
// context), so it takes an optional `t` (useLanguage()'s translate fn) with a DICT.vi
// fallback for callers without context — same pattern as office-message-line.ts.
import { DICT } from './i18n/dictionary'
import type { UiKey } from './i18n/dictionary'
import type { PendingAction } from './types'

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

const defaultT: Translate = (key, params) => {
  let str: string = DICT.vi[key]
  if (params) for (const [k, v] of Object.entries(params)) str = str.replaceAll(`{${k}}`, String(v))
  return str
}

export interface ActionSummary {
  text: string // the human-readable line
  external: boolean // true ⇒ goes OUTSIDE (stakeholder channel / email) — surface prominently
}

function s(action: PendingAction, key: string): string {
  const v = action.args?.[key]
  return v === undefined || v === null ? '' : String(v)
}

/** Summarise an action + whether it leaves the org (external). Unknown → readable fallback. */
export function summarizeAction(action: PendingAction, reason = '', t: Translate = defaultT): ActionSummary {
  const type = (action.type ?? '').toLowerCase()
  const unknown = t('actionSummary.unknownValue')

  // Email always leaves the org. `to` is a recipient LIST on the backend (email_write.py).
  if (type === 'email_send') {
    const to = Array.isArray(action.to) ? action.to.join(', ') : (action.to ?? '')
    const subject = action.subject ?? ''
    return {
      text: subject
        ? t('actionSummary.emailWithSubject', { to: to || unknown, subject })
        : t('actionSummary.email', { to: to || unknown }),
      external: true,
    }
  }

  if (type === 'gh_cli') {
    const argv = (action.argv ?? []).map((a) => String(a).toLowerCase())
    if (argv[0] === 'pr') {
      const num = action.argv?.find((a) => /^\d+$/.test(String(a))) ?? '?'
      if (argv.includes('merge')) return { text: t('actionSummary.ghMergePr', { num }), external: false }
      if (argv.includes('close')) return { text: t('actionSummary.ghClosePr', { num }), external: false }
      if (argv.includes('ready')) return { text: t('actionSummary.ghReadyPr', { num }), external: false }
    }
    return { text: t('actionSummary.ghCommand', { argv: (action.argv ?? []).slice(0, 3).join(' ') || unknown }), external: false }
  }

  if (type === 'mcp_tool') {
    const server = (action.server ?? '').toLowerCase()
    const tool = (action.tool ?? '').toLowerCase()

    if (server === 'jira') {
      if (tool === 'createissue')
        return {
          text: t('actionSummary.jiraCreate', {
            summary: s(action, 'summary') || unknown,
            project: s(action, 'projectKey') || unknown,
          }),
          external: false,
        }
      if (tool === 'closeissue') return { text: t('actionSummary.jiraClose', { issueKey: s(action, 'issueKey') }), external: false }
      if (tool === 'transitionissue') return { text: t('actionSummary.jiraTransition', { issueKey: s(action, 'issueKey') }), external: false }
      if (tool === 'assignissue') return { text: t('actionSummary.jiraAssign', { issueKey: s(action, 'issueKey') }), external: false }
    }

    if (server === 'confluence' && tool === 'createpage')
      return { text: t('actionSummary.confluenceCreate', { title: s(action, 'title') || unknown }), external: false }

    if (server === 'slack' && (tool === 'post_message' || tool === 'postmessage')) {
      const channel = s(action, 'channel') || unknown
      // The gateway routes an external-channel post to Lớp B with a reason that names it
      // "external" (hard_block.py). We can't see external_channels client-side, so we trust
      // that marker. LIMITATION (see review H1): if a future chat-command force-queues an
      // external post with a reason lacking this token, it would show as internal — the real
      // fix is a structured is_external flag from the backend approvals view. Until then the
      // catalog has only internal chat-commands, so this holds.
      //
      // NOTE: this substring check matches the backend's own reason text (data, not FE copy) —
      // it must stay matching the literal Vietnamese the API returns, regardless of UI language.
      const isExternal = /external|stakeholder|ra ngoài/i.test(reason)
      return isExternal
        ? { text: t('actionSummary.slackExternal', { channel }), external: true }
        : { text: t('actionSummary.slackInternal', { channel }), external: false }
    }

    if (server === 'linear' && tool === 'createcomment') {
      const issue = s(action, 'issueId') || s(action, 'issueKey')
      return { text: issue ? t('actionSummary.linearCommentIssue', { issue }) : t('actionSummary.linearComment'), external: false }
    }

    // Known type, unmapped tool → readable fallback (server · tool), never blank.
    return { text: t('actionSummary.mcpFallback', { server: action.server ?? '?', tool: action.tool ?? '?' }), external: false }
  }

  if (type === 'telegram_send')
    return { text: t('actionSummary.telegramSend'), external: false }

  // v31 native types. gws writes touch COMPANY Sheets/Docs — internal assets
  // (external:false matches the server's needs_interrupt semantics for gws_write).
  if (type === 'gws_write') {
    const argv = (action.argv ?? []).map((a) => String(a))
    const lower = argv.map((a) => a.toLowerCase())
    if (lower[0] === 'sheets' && lower[1] === '+append')
      return { text: t('actionSummary.gwsSheetAppend'), external: false }
    if (lower[0] === 'docs' && lower[1] === 'documents' && lower[2] === 'create')
      return { text: t('actionSummary.gwsDocCreate'), external: false }
    if (lower[0] === 'docs' && lower[1] === '+write')
      return { text: t('actionSummary.gwsDocWrite'), external: false }
    return { text: t('actionSummary.gwsCommand', { argv: argv.slice(0, 3).join(' ') || unknown }), external: false }
  }

  if (type === 'schedule_update') {
    const entries = Object.entries(action.schedule ?? {})
      .map(([k, v]) => `${k} → ${String(v)}`)
      .join(', ')
    return { text: t('actionSummary.scheduleUpdate', { entries: entries || unknown }), external: false }
  }

  if (type === 'team_task_create')
    return {
      text: t('actionSummary.teamTaskCreate', { title: action.title ?? unknown, assignee: action.assignee ?? '?' }),
      external: false,
    }

  if (type === 'team_task_move')
    return {
      text: t('actionSummary.teamTaskMove', { taskId: action.task_id ?? '?', status: action.status ?? '?' }),
      external: false,
    }

  // Fully unknown → best-effort readable line from whatever we have.
  const hint = action.tool || action.server || action.type || (action.argv ?? []).slice(0, 3).join(' ')
  return { text: t('actionSummary.unknownAction', { hint: hint || t('actionSummary.unknownActionFallback') }), external: false }
}
