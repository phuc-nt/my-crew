// v9 P1 — human-readable Vietnamese summary of a Lớp B action for the approve dialog.
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
import type { PendingAction } from './types'

export interface ActionSummary {
  text: string // the human Vietnamese line
  external: boolean // true ⇒ goes OUTSIDE (stakeholder channel / email) — surface prominently
}

function s(action: PendingAction, key: string): string {
  const v = action.args?.[key]
  return v === undefined || v === null ? '' : String(v)
}

/** Summarise an action + whether it leaves the org (external). Unknown → readable fallback. */
export function summarizeAction(action: PendingAction, reason = ''): ActionSummary {
  const type = (action.type ?? '').toLowerCase()

  // Email always leaves the org. `to` is a recipient LIST on the backend (email_write.py).
  if (type === 'email_send') {
    const to = Array.isArray(action.to) ? action.to.join(', ') : (action.to ?? '')
    const subject = action.subject ?? ''
    return { text: `Gửi email tới ${to || '(chưa rõ)'}${subject ? `: ${subject}` : ''}`, external: true }
  }

  if (type === 'gh_cli') {
    const argv = (action.argv ?? []).map((a) => String(a).toLowerCase())
    if (argv[0] === 'pr') {
      const num = action.argv?.find((a) => /^\d+$/.test(String(a))) ?? '?'
      if (argv.includes('merge')) return { text: `Gộp (merge) PR #${num}`, external: false }
      if (argv.includes('close')) return { text: `Đóng PR #${num}`, external: false }
      if (argv.includes('ready')) return { text: `Chuyển PR #${num} sang sẵn sàng review`, external: false }
    }
    return { text: `Lệnh GitHub: ${(action.argv ?? []).slice(0, 3).join(' ') || '(chưa rõ)'}`, external: false }
  }

  if (type === 'mcp_tool') {
    const server = (action.server ?? '').toLowerCase()
    const tool = (action.tool ?? '').toLowerCase()

    if (server === 'jira') {
      if (tool === 'createissue')
        return { text: `Tạo ticket Jira '${s(action, 'summary') || '(chưa rõ)'}' trong dự án ${s(action, 'projectKey') || '(chưa rõ)'}`, external: false }
      if (tool === 'closeissue') return { text: `Đóng issue Jira ${s(action, 'issueKey')}`, external: false }
      if (tool === 'transitionissue') return { text: `Chuyển trạng thái issue Jira ${s(action, 'issueKey')}`, external: false }
      if (tool === 'assignissue') return { text: `Giao issue Jira ${s(action, 'issueKey')}`, external: false }
    }

    if (server === 'confluence' && tool === 'createpage')
      return { text: `Tạo trang Confluence '${s(action, 'title') || '(chưa rõ)'}'`, external: false }

    if (server === 'slack' && (tool === 'post_message' || tool === 'postmessage')) {
      const channel = s(action, 'channel') || '(chưa rõ)'
      // The gateway routes an external-channel post to Lớp B with a reason that names it
      // "external" (hard_block.py). We can't see external_channels client-side, so we trust
      // that marker. LIMITATION (see review H1): if a future chat-command force-queues an
      // external post with a reason lacking this token, it would show as internal — the real
      // fix is a structured is_external flag from the backend approvals view. Until then the
      // catalog has only internal chat-commands, so this holds.
      const isExternal = /external|stakeholder|ra ngoài/i.test(reason)
      return isExternal
        ? { text: `⚠️ Đăng tin RA NGOÀI, tới kênh Slack ${channel}`, external: true }
        : { text: `Đăng tin vào kênh Slack ${channel}`, external: false }
    }

    if (server === 'linear' && tool === 'createcomment') {
      const issue = s(action, 'issueId') || s(action, 'issueKey')
      return { text: issue ? `Bình luận issue Linear ${issue}` : 'Bình luận trên Linear', external: false }
    }

    // Known type, unmapped tool → readable fallback (server · tool), never blank.
    return { text: `Hành động ${action.server ?? '?'} · ${action.tool ?? '?'}`, external: false }
  }

  if (type === 'telegram_send')
    return { text: 'Gửi tin nhắn Telegram', external: false }

  // v31 native types. gws writes touch COMPANY Sheets/Docs — internal assets
  // (external:false matches the server's needs_interrupt semantics for gws_write).
  if (type === 'gws_write') {
    const argv = (action.argv ?? []).map((a) => String(a))
    const lower = argv.map((a) => a.toLowerCase())
    if (lower[0] === 'sheets' && lower[1] === '+append')
      return { text: 'Thêm dòng vào Google Sheet của công ty', external: false }
    if (lower[0] === 'docs' && lower[1] === 'documents' && lower[2] === 'create')
      return { text: 'Tạo Google Doc mới (rỗng)', external: false }
    if (lower[0] === 'docs' && lower[1] === '+write')
      return { text: 'Ghi nội dung vào một Google Doc', external: false }
    return { text: `Lệnh Google Workspace: ${argv.slice(0, 3).join(' ') || '(chưa rõ)'}`, external: false }
  }

  if (type === 'schedule_update') {
    const entries = Object.entries(action.schedule ?? {})
      .map(([k, v]) => `${k} → ${String(v)}`)
      .join(', ')
    return { text: `Agent tự đổi lịch chạy: ${entries || '(chưa rõ)'}`, external: false }
  }

  if (type === 'team_task_create')
    return {
      text: `Đề xuất thẻ việc '${action.title ?? '(chưa rõ)'}' giao ${action.assignee ?? '?'}`,
      external: false,
    }

  if (type === 'team_task_move')
    return {
      text: `Chuyển thẻ việc ${action.task_id ?? '?'} sang '${action.status ?? '?'}'`,
      external: false,
    }

  // Fully unknown → best-effort readable line from whatever we have.
  const hint = action.tool || action.server || action.type || (action.argv ?? []).slice(0, 3).join(' ')
  return { text: `Hành động: ${hint || '(không rõ loại)'}`, external: false }
}
